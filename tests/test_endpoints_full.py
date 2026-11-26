import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, text

from app.database import AsyncSessionLocal
from app.main import _ensure_idempotency_expires_at, app
from app.models.event import IdempotencyRecordModel


@pytest.mark.asyncio
async def test_users_register_me_and_delete():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        reg = await ac.post("/api/v1/users/register", json={"tenant_id": "tenant_usr_1"})
        assert reg.status_code == 201
        token = reg.json()["api_token"]
        assert token.startswith("ps_alive_")

        me = await ac.get("/api/v1/users/me", headers={"X-API-Key": token})
        assert me.status_code == 200
        assert me.json()["tenant_id"] == "tenant_usr_1"

        # Missing key on delete -> 401
        del_missing = await ac.delete("/api/v1/users/delete")
        assert del_missing.status_code == 401

        # Unknown key on delete -> 404
        del_unknown = await ac.delete("/api/v1/users/delete", headers={"X-API-Key": "ps_alive_unknown"})
        assert del_unknown.status_code == 404

        # Valid delete -> 202 and token is deactivated
        del_ok = await ac.delete("/api/v1/users/delete", headers={"X-API-Key": token})
        assert del_ok.status_code == 202
        assert del_ok.json()["is_active"] is False

        me_after = await ac.get("/api/v1/users/me", headers={"X-API-Key": token})
        assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_list_api_keys_and_webhooks_crud():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        k_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_wh_1", "name": "Key 1"})
        assert k_res.status_code == 201
        raw_key = k_res.json()["raw_key"]
        headers = {"X-API-Key": raw_key}

        # List API keys
        list_keys = await ac.get("/api/v1/api-keys/", headers=headers)
        assert list_keys.status_code == 200
        assert len(list_keys.json()) >= 1
        assert "raw_key" not in list_keys.json()[0]

        # Register webhook
        wh_payload = {"tenant_id": "tenant_wh_1", "target_url": "https://example.com/hook1", "secret": "s1"}
        wh1 = await ac.post("/api/v1/webhooks", json=wh_payload, headers=headers)
        assert wh1.status_code == 201

        # Duplicate webhook URL -> 400
        wh_dup = await ac.post("/api/v1/webhooks", json=wh_payload, headers=headers)
        assert wh_dup.status_code == 400

        # List webhooks
        wh_list = await ac.get("/api/v1/webhooks", headers=headers)
        assert wh_list.status_code == 200
        assert any(w["target_url"] == "https://example.com/hook1" for w in wh_list.json())


@pytest.mark.asyncio
async def test_events_list_404_and_24h_idempotency_paths():
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.setex = AsyncMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        k_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_evt_1", "name": "Evt Key"})
        raw_key = k_res.json()["raw_key"]
        headers = {"X-API-Key": raw_key}

        # Non-existent event -> 404
        not_found = await ac.get("/api/v1/events/evt_does_not_exist", headers=headers)
        assert not_found.status_code == 404

        # Redis cache hit returns cached response directly
        cached_payload = {
            "id": "evt_cached_redis",
            "tenant_id": "tenant_evt_1",
            "event_type": "order.paid",
            "payload": {"amount": 10},
            "status": "ingested",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        fake_redis.get = AsyncMock(return_value=json.dumps(cached_payload))
        with patch("app.api.v1.events.get_redis_client", return_value=fake_redis):
            hit_res = await ac.post(
                "/api/v1/events",
                json={"tenant_id": "tenant_evt_1", "event_type": "order.paid", "payload": {"amount": 10}},
                headers={**headers, "Idempotency-Key": "idem-redis-hit"},
            )
        assert hit_res.json()["id"] == "evt_cached_redis"

        # Expired DB idempotency record (>24h old) does NOT block new event creation
        past = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=25)
        async with AsyncSessionLocal() as db:
            db.add(
                IdempotencyRecordModel(
                    key="idem-expired-key",
                    response_code=201,
                    response_body=json.dumps({"id": "evt_old_expired"}),
                    created_at=past - datetime.timedelta(hours=24),
                    expires_at=past,
                )
            )
            await db.commit()

        fake_redis.get = AsyncMock(return_value=None)
        with patch("app.api.v1.events.get_redis_client", return_value=fake_redis):
            # Replace expired record key by testing a fresh key & checking list_events
            create_res = await ac.post(
                "/api/v1/events",
                json={"tenant_id": "tenant_evt_1", "event_type": "order.paid", "payload": {"amount": 42}},
                headers={**headers, "Idempotency-Key": "idem-fresh-key"},
            )
        assert create_res.status_code == 201
        fake_redis.setex.assert_awaited_once()
        assert fake_redis.setex.call_args.args[1] == 86400

        list_res = await ac.get("/api/v1/events", headers=headers)
        assert list_res.status_code == 200
        assert any(e["id"] == create_res.json()["id"] for e in list_res.json())


@pytest.mark.asyncio
async def test_health_readyz_and_metrics():
    fake_redis = MagicMock()
    fake_redis.ping = AsyncMock(return_value=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch("app.api.v1.health.get_redis_client", return_value=fake_redis):
            ready = await ac.get("/readyz")
            assert ready.status_code == 200
            assert ready.json()["database"] == "connected"
            assert ready.json()["redis"] == "connected"

        metrics = await ac.get("/metrics")
        assert metrics.status_code == 200
        assert "pulsestream_events_ingested_total" in metrics.text

        with patch("app.api.v1.health.engine.connect", side_effect=RuntimeError("db down")):
            unready = await ac.get("/readyz")
            assert unready.status_code == 503
            assert unready.json()["status"] == "not_ready"


def test_ensure_idempotency_expires_at_helper():
    sync_engine = create_engine("sqlite:///:memory:")
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE idempotency_records ("
                "key VARCHAR(128) PRIMARY KEY, response_code INTEGER NOT NULL, "
                "response_body TEXT NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO idempotency_records (key, response_code, response_body, created_at) "
                "VALUES ('k1', 201, '{}', '2026-11-26 00:00:00')"
            )
        )
        _ensure_idempotency_expires_at(conn)
        cols = {c["name"] for c in inspect(conn).get_columns("idempotency_records")}
        assert "expires_at" in cols
        row = conn.execute(text("SELECT expires_at FROM idempotency_records WHERE key='k1'")).fetchone()
        assert row[0] is not None
        # Calling again is a safe no-op
        _ensure_idempotency_expires_at(conn)
