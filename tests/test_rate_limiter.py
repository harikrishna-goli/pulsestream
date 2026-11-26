from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.middleware.rate_limiter import (
    InMemoryTokenBucketRateLimiter,
    RedisTokenBucketRateLimiter,
    evluate_rate_limit,
)


@pytest.mark.asyncio
async def test_evaluate_rate_limit_allowed_and_blocked():
    mock_redis = MagicMock()
    mock_runner = AsyncMock(return_value=[1, 59, 0])
    mock_redis.register_script.return_value = mock_runner

    allowed, remaining, retry_after = await evluate_rate_limit(mock_redis, "tenant:abc")
    assert allowed is True
    assert remaining == 59
    assert retry_after == 0

    mock_runner.return_value = [0, 0, 12]
    allowed, remaining, retry_after = await evluate_rate_limit(mock_redis, "tenant:abc")
    assert allowed is False
    assert remaining == 0
    assert retry_after == 12


@pytest.mark.asyncio
async def test_evaluate_rate_limit_fail_open_and_fail_closed():
    mock_redis = MagicMock()
    mock_redis.register_script.return_value = AsyncMock(side_effect=ConnectionError("Redis down"))

    with patch.object(settings, "RATE_LIMIT_FAIL_OPEN", True):
        allowed, remaining, retry_after = await evluate_rate_limit(mock_redis, "ip:1.2.3.4", limit=60)
        assert allowed is True
        assert remaining == 60
        assert retry_after == 0

    with patch.object(settings, "RATE_LIMIT_FAIL_OPEN", False):
        with pytest.raises(HTTPException) as exc_info:
            await evluate_rate_limit(mock_redis, "ip:1.2.3.4", limit=60)
        assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_redis_middleware_headers_and_429():
    mini_app = FastAPI()
    mini_app.add_middleware(RedisTokenBucketRateLimiter, rate_limit=2)

    @mini_app.get("/ping")
    async def ping():
        return {"ok": True}

    @mini_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    with patch("app.middleware.rate_limiter.get_redis_client", return_value=MagicMock()):
        with patch("app.middleware.rate_limiter.evluate_rate_limit", new_callable=AsyncMock) as mock_eval:
            async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://test") as ac:
                # Health endpoint bypasses rate limiter
                h_res = await ac.get("/healthz")
                assert h_res.status_code == 200
                mock_eval.assert_not_called()

                # Allowed request sets rate-limit headers
                mock_eval.return_value = (True, 1, 0)
                ok_res = await ac.get("/ping", headers={"X-API-Key": "ps_alive_secret"})
                assert ok_res.status_code == 200
                assert ok_res.headers["X-RateLimit-Limit"] == "2"
                assert ok_res.headers["X-RateLimit-Remaining"] == "1"

                # Blocked request returns 429 JSONResponse
                mock_eval.return_value = (False, 0, 15)
                blocked_res = await ac.get("/ping")
                assert blocked_res.status_code == 429
                assert blocked_res.headers["Retry-After"] == "15"
                assert blocked_res.headers["X-RateLimit-Remaining"] == "0"
                assert "15 seconds" in blocked_res.json()["detail"]


@pytest.mark.asyncio
async def test_in_memory_rate_limiter_allows_then_blocks():
    mini_app = FastAPI()
    mini_app.add_middleware(InMemoryTokenBucketRateLimiter, rate_limit=2, window_seconds=60)

    @mini_app.get("/ping")
    async def ping():
        return {"ok": True}

    @mini_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://test") as ac:
        assert (await ac.get("/healthz")).status_code == 200
        assert (await ac.get("/ping")).status_code == 200
        assert (await ac.get("/ping")).status_code == 200
        with pytest.raises(HTTPException) as exc_info:
            await ac.get("/ping")
        assert exc_info.value.status_code == 429
