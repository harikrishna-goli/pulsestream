import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import engine, Base

@pytest.fixture(scope="session", autouse=True)
def init_db():
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init())

@pytest.mark.asyncio
async def test_health_and_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r_health = await ac.get("/healthz")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        r_ready = await ac.get("/readyz")
        assert r_ready.status_code == 200
        assert r_ready.json()["status"] == "ready"

@pytest.mark.asyncio
async def test_event_ingestion_and_retrieval():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        key_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_test", "name": "Test Key"})
        assert key_res.status_code == 201
        headers = {"X-API-Key": key_res.json()["raw_key"]}

        payload = {
            "tenant_id": "tenant_test",
            "event_type": "user.signup",
            "payload": {"email": "alice@example.com", "plan": "pro"}
        }
        res = await ac.post("/api/v1/events", json=payload, headers=headers)
        assert res.status_code == 201
        data = res.json()
        assert data["tenant_id"] == "tenant_test"
        assert "evt_" in data["id"]

        # Retrieve event
        get_res = await ac.get(f"/api/v1/events/{data['id']}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["id"] == data["id"]

@pytest.mark.asyncio
async def test_idempotency_key_deduplication():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        key_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_acme", "name": "Acme Key"})
        assert key_res.status_code == 201
        raw_key = key_res.json()["raw_key"]

        payload = {
            "tenant_id": "tenant_acme",
            "event_type": "invoice.paid",
            "payload": {"invoice_id": "inv_999", "amount": 250.0}
        }
        headers = {
            "X-API-Key": raw_key,
            "Idempotency-Key": "test-idempotency-key-12345"
        }
        
        # 1st call -> Creates event
        res1 = await ac.post("/api/v1/events", json=payload, headers=headers)
        assert res1.status_code == 201
        event_id_1 = res1.json()["id"]

        # 2nd call with same Idempotency-Key -> Returns identical cached response
        res2 = await ac.post("/api/v1/events", json=payload, headers=headers)
        assert res2.status_code == 201 or res2.status_code == 200
        event_id_2 = res2.json()["id"]

        assert event_id_1 == event_id_2
