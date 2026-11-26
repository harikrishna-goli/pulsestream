"""
FR-4: Asynchronous Reliable Dispatching (HMAC-SHA256).
FR-5: Exponential Backoff (up to 5 attempts with randomized jitter) & Dead Letter Queue (DLQ).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import random
import uuid
from typing import Any, Dict, Optional

import httpx

from app.api.v1.health import WEBHOOKS_DELIVERED_TOTAL, WEBHOOKS_DLQ_TOTAL
from app.database import AsyncSessionLocal
from app.models.event import DeadLetterQueueModel

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 0.5


def generate_hmac_signature(secret: str, payload: Dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


async def _move_to_dlq(
    event_id: str,
    tenant_id: str,
    target_url: str,
    payload: Dict[str, Any],
    failure_reason: str,
    last_response_code: Optional[int],
) -> None:
    """Persist unrecoverable webhook delivery failure to DeadLetterQueueModel."""
    try:
        async with AsyncSessionLocal() as db:
            dlq_entry = DeadLetterQueueModel(
                id=f"dlq_{uuid.uuid4().hex[:16]}",
                outbox_id=f"out_{uuid.uuid4().hex[:16]}",
                event_id=event_id,
                tenant_id=tenant_id,
                destination_url=target_url,
                payload=payload,
                failure_reason=failure_reason,
                last_response_code=last_response_code,
            )
            db.add(dlq_entry)
            await db.commit()
            WEBHOOKS_DLQ_TOTAL.inc()
            logger.error(
                "Webhook moved to DLQ (event_id=%s, url=%s, code=%s, reason=%s)",
                event_id,
                target_url,
                last_response_code,
                failure_reason,
            )
    except Exception as exc:
        logger.exception("Failed to write webhook failure to DLQ: %s", exc)


async def dispatch_webhook(
    target_url: str,
    secret: str,
    payload: Dict[str, Any],
    event_id: str = "unknown",
    tenant_id: str = "unknown",
) -> bool:
    signature = generate_hmac_signature(secret, payload)
    headers = {
        "Content-Type": "application/json",
        "X-PulseStream-Signature": f"sha256={signature}",
        "User-Agent": "PulseStream-Dispatcher/1.0",
    }

    last_status_code: Optional[int] = None
    last_error: str = "Unknown error"

    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.post(target_url, json=payload, headers=headers)
                last_status_code = resp.status_code

                if resp.is_success:
                    WEBHOOKS_DELIVERED_TOTAL.inc()
                    logger.info(
                        "Webhook delivered (event_id=%s, url=%s, attempt=%d/%d, status=%d)",
                        event_id,
                        target_url,
                        attempt,
                        MAX_RETRIES,
                        resp.status_code,
                    )
                    return True

                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code < 500:
                    # 4xx client error is non-retryable
                    break

            except Exception as exc:
                last_status_code = None
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                jitter = random.uniform(0, backoff * 0.5)
                delay = round(backoff + jitter, 3)
                logger.warning(
                    "Webhook attempt %d/%d failed (event_id=%s, url=%s, error=%s). Retrying in %.3fs...",
                    attempt,
                    MAX_RETRIES,
                    event_id,
                    target_url,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

    await _move_to_dlq(
        event_id=event_id,
        tenant_id=tenant_id,
        target_url=target_url,
        payload=payload,
        failure_reason=last_error,
        last_response_code=last_status_code,
    )
    return False
