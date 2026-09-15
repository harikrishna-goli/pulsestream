import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_create_api_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {"tenant_id": "tenant_alpha", "name": "Ingestion Key"}
        response = await ac.post("/api/v1/api-keys/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["tenant_id"] == "tenant_alpha"
        assert len(data["raw_key"]) >= 32
        assert data["key_prefix"].endswith("...")
        assert "key_" in data["id"]

@pytest.mark.asyncio
async def test_access_without_key_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        event_payload = {
            "tenant_id": "tenant_alpha",
            "event_type": "order.created",
            "payload": {"price": 100}
        }
        res = await ac.post("/api/v1/events", json=event_payload)
        
        assert res.status_code == 401
        assert res.json()["detail"] == "API Key missing"

@pytest.mark.asyncio
async def test_access_with_invalid_key_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"X-API-Key": "fake_random_secret_string"}
        res = await ac.post(
            "/api/v1/events",
            json={"tenant_id": "tenant_alpha", "event_type": "test", "payload": {}},
            headers=headers
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid API Key"

@pytest.mark.asyncio
async def test_access_with_valid_key_accepted():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create key
        key_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_beta", "name": "Key"})
        assert key_res.status_code == 201
        raw_key = key_res.json()["raw_key"]

        # 2. Ingest event with the key
        headers = {"X-API-Key": raw_key}
        res = await ac.post(
            "/api/v1/events",
            json={"tenant_id": "tenant_beta", "event_type": "payment.received", "payload": {"amount": 50}},
            headers=headers
        )
        assert res.status_code == 201
        assert res.json()["tenant_id"] == "tenant_beta"

@pytest.mark.asyncio
async def test_revoke_key_immediately_cuts_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create key
        create_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_gamma", "name": "Temp Key"})
        data = create_res.json()
        key_id = data["id"]
        raw_key = data["raw_key"]
        headers = {"X-API-Key": raw_key}

        # 2. Revoke the key
        del_res = await ac.delete(f"/api/v1/api-keys/{key_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["is_active"] is False

        # 3. Subsequent request with the same revoked key MUST fail
        subsequent_res = await ac.post(
            "/api/v1/events",
            json={"tenant_id": "tenant_gamma", "event_type": "test", "payload": {}},
            headers=headers
        )
        assert subsequent_res.status_code == 401
        assert subsequent_res.json()["detail"] == "Invalid API Key"

@pytest.mark.asyncio
async def test_cross_tenant_revocation_prevented():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Tenant 1 key
        t1_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_one", "name": "T1 Key"})
        t1_key_id = t1_res.json()["id"]

        # Tenant 2 key
        t2_res = await ac.post("/api/v1/api-keys/", json={"tenant_id": "tenant_two", "name": "T2 Key"})
        t2_raw_key = t2_res.json()["raw_key"]

        # Tenant 2 tries to delete Tenant 1's key
        attack_res = await ac.delete(
            f"/api/v1/api-keys/{t1_key_id}",
            headers={"X-API-Key": t2_raw_key}
        )
        assert attack_res.status_code == 404