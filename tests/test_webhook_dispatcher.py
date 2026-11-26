from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.event import DeadLetterQueueModel
from app.services.webhook_dispatcher import dispatch_webhook, generate_hmac_signature


def test_generate_hmac_signature_is_sorted_and_deterministic():
    sig1 = generate_hmac_signature("sec", {"b": 2, "a": 1})
    sig2 = generate_hmac_signature("sec", {"a": 1, "b": 2})
    assert sig1 == sig2
    assert len(sig1) == 64


@pytest.mark.asyncio
async def test_dispatch_webhook_succeeds_first_try():
    mock_resp = MagicMock(status_code=200, is_success=True)
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    with patch("app.services.webhook_dispatcher.httpx.AsyncClient", return_value=mock_client):
        ok = await dispatch_webhook(
            target_url="https://example.com/hook",
            secret="whsec_123",
            payload={"event_id": "evt_1"},
            event_id="evt_1",
            tenant_id="tenant_1",
        )
    assert ok is True
    assert mock_client.post.await_count == 1
    sent_headers = mock_client.post.call_args.kwargs["headers"]
    assert sent_headers["X-PulseStream-Signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_dispatch_webhook_retries_5xx_then_succeeds():
    fail_resp = MagicMock(status_code=503, is_success=False, text="unavailable")
    ok_resp = MagicMock(status_code=200, is_success=True)
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.side_effect = [fail_resp, fail_resp, ok_resp]

    with patch("app.services.webhook_dispatcher.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhook_dispatcher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            ok = await dispatch_webhook(
                target_url="https://example.com/hook",
                secret="whsec_123",
                payload={"event_id": "evt_retry"},
                event_id="evt_retry",
                tenant_id="tenant_1",
            )
    assert ok is True
    assert mock_client.post.await_count == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_webhook_4xx_moves_directly_to_dlq():
    bad_resp = MagicMock(status_code=400, is_success=False, text="bad payload")
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = bad_resp

    with patch("app.services.webhook_dispatcher.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhook_dispatcher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            ok = await dispatch_webhook(
                target_url="https://example.com/400",
                secret="whsec_123",
                payload={"event_id": "evt_400"},
                event_id="evt_400",
                tenant_id="tenant_dlq_400",
            )
    assert ok is False
    assert mock_client.post.await_count == 1
    mock_sleep.assert_not_awaited()

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.event_id == "evt_400"))
        dlq = res.scalar_one_or_none()
        assert dlq is not None
        assert dlq.last_response_code == 400
        assert "HTTP 400" in dlq.failure_reason


@pytest.mark.asyncio
async def test_dispatch_webhook_5_timeouts_moves_to_dlq():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.side_effect = httpx.ReadTimeout("timed out")

    with patch("app.services.webhook_dispatcher.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.webhook_dispatcher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            ok = await dispatch_webhook(
                target_url="https://example.com/timeout",
                secret="whsec_123",
                payload={"event_id": "evt_timeout"},
                event_id="evt_timeout",
                tenant_id="tenant_dlq_timeout",
            )
    assert ok is False
    assert mock_client.post.await_count == 5
    assert mock_sleep.await_count == 4

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.event_id == "evt_timeout"))
        dlq = res.scalar_one_or_none()
        assert dlq is not None
        assert dlq.last_response_code is None
        assert "ReadTimeout" in dlq.failure_reason
