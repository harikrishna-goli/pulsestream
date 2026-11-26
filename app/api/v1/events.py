import uuid
import json
import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.middleware.auth import verify_api_key
from app.database import get_db
from app.models.event import EventModel, IdempotencyRecordModel, WebhookEndpointModel
from app.schemas.event import EventCreate, EventResponse
from app.services.webhook_dispatcher import dispatch_webhook
from app.services.redis import get_redis_client
from app.api.v1.health import EVENTS_INGESTED_TOTAL

router = APIRouter(prefix="/events", tags=["Events"])

IDEMPOTENCY_TTL_SECONDS = 86400  # 24 hours

async def _get_idempotency_response(idempotency_key: str, db: AsyncSession) -> dict | None:
    """Check Redis first (fast), fall back to DB (source of truth)."""
    redis = get_redis_client()

    # 1. Redis cache lookup (fast path)
    try:
        cached = await redis.get(f"idem:{idempotency_key}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis unavailable — fall through to DB

    # 2. DB lookup (source of truth) — only if within 24hr window
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    stmt = select(IdempotencyRecordModel).where(
        IdempotencyRecordModel.key == idempotency_key,
        IdempotencyRecordModel.expires_at > now   # enforce 24hr window
    )
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    if record:
        return json.loads(record.response_body)

    return None

async def _save_idempotency(idempotency_key: str, response_data: dict, db: AsyncSession):
    """Save to both Redis (TTL 24hr) and DB (with expires_at)."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    expires_at = now + datetime.timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
    serialized = json.dumps(response_data, default=str)

    # 1. Write to Redis with 24hr TTL
    redis = get_redis_client()
    try:
        await redis.setex(f"idem:{idempotency_key}", IDEMPOTENCY_TTL_SECONDS, serialized)
    except Exception:
        pass  # Redis unavailable — DB is the fallback

    # 2. Write to DB with expires_at for durability
    idem_db = IdempotencyRecordModel(
        key=idempotency_key,
        response_code=201,
        response_body=serialized,
        expires_at=expires_at,
    )
    db.add(idem_db)
    await db.commit()

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def ingest_event(
    event_in: EventCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(verify_api_key),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    effective_idem_key = idempotency_key or x_idempotency_key

    # 1. Idempotency Check (Redis → DB, 24hr window)
    if effective_idem_key:
        cached_response = await _get_idempotency_response(effective_idem_key, db)
        if cached_response:
            return cached_response

    # 2. Ingest Event
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    event_db = EventModel(
        id=event_id,
        tenant_id=tenant_id,
        event_type=event_in.event_type,
        payload=event_in.payload,
        status="ingested"
    )
    db.add(event_db)
    
    # 3. Dispatch to active webhooks in background
    wh_stmt = select(WebhookEndpointModel).where(
        WebhookEndpointModel.tenant_id == tenant_id,
        WebhookEndpointModel.is_active == True
    )
    wh_res = await db.execute(wh_stmt)
    webhooks = wh_res.scalars().all()
    for wh in webhooks:
        background_tasks.add_task(
            dispatch_webhook,
            target_url=wh.target_url,
            secret=wh.secret,
            payload={"event_id": event_id, "type": event_in.event_type, "data": event_in.payload},
            event_id=event_id,
            tenant_id=tenant_id,
        )

    # 4. Commit event
    await db.commit()
    await db.refresh(event_db)
    EVENTS_INGESTED_TOTAL.inc()
    
    # 5. Save idempotency record (Redis 24hr TTL + DB with expires_at)
    if effective_idem_key:
        response_data = EventResponse.model_validate(event_db).model_dump()
        await _save_idempotency(effective_idem_key, response_data, db)

    return event_db

@router.get("", response_model=list[EventResponse])
async def list_events(
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(verify_api_key),
):
    stmt = select(EventModel).where(EventModel.tenant_id == tenant_id).order_by(EventModel.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db),
                    tenant_id: str = Depends(verify_api_key)):
    
    
    stmt = select(EventModel).where(EventModel.id == event_id)
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
