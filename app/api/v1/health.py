from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from app.database import engine
from app.services.redis import get_redis_client

router = APIRouter(tags=["Health & Metrics"])

EVENTS_INGESTED_TOTAL = Counter(
    "pulsestream_events_ingested_total",
    "Total events ingested",
)
WEBHOOKS_DELIVERED_TOTAL = Counter(
    "pulsestream_webhooks_delivered_total",
    "Total webhooks delivered successfully",
)
WEBHOOKS_DLQ_TOTAL = Counter(
    "pulsestream_webhooks_dlq_total",
    "Total webhooks moved to Dead Letter Queue",
)
REQUEST_DURATION_SECONDS = Histogram(
    "pulsestream_request_duration_seconds",
    "Latency histogram",
)


@router.get("/healthz")
async def healthz():
    """Liveness probe: confirms the FastAPI process is alive (no external I/O)."""
    return {"status": "ok", "service": "PulseStream Event Engine"}


@router.get("/readyz")
async def readyz():
    """Readiness probe: checks PostgreSQL and Redis connectivity."""
    db_status = "disconnected"
    redis_status = "disconnected"

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"

    try:
        redis = get_redis_client()
        await redis.ping()
        redis_status = "connected"
    except Exception as exc:
        redis_status = f"error: {exc}"

    is_ready = db_status == "connected"
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "database": db_status,
        "redis": redis_status,
    }
    if not is_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


@router.get("/metrics")
async def metrics():
    """Prometheus plain-text exposition."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
