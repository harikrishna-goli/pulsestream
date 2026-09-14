import uuid
import json
from fastapi import APIRouter, Depends, Header, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.middleware.auth import verify_api_key
from app.database import get_db
from app.models.event import EventModel, IdempotencyRecordModel, WebhookEndpointModel
from app.schemas.event import EventCreate, EventResponse
from app.services.webhook_dispatcher import dispatch_webhook

router = APIRouter(prefix="/events", tags=["Events"])

@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def ingest_event(
    event_in: EventCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(verify_api_key),
    idempotency_key: str = Header(None, alias="Idempotency-Key")
):
    
    # 1. Idempotency Check
    if idempotency_key:
        stmt = select(IdempotencyRecordModel).where(IdempotencyRecordModel.key == idempotency_key)
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            return json.loads(record.response_body)

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
            payload={"event_id": event_id, "type": event_in.event_type, "data": event_in.payload}
        )

    # 4. Commit and Save Idempotency
    await db.commit()
    await db.refresh(event_db)
    
    response_data = EventResponse.model_validate(event_db).model_dump()
    if idempotency_key:
        idem_db = IdempotencyRecordModel(
            key=idempotency_key,
            response_code=201,
            response_body=json.dumps(response_data, default=str)
        )
        db.add(idem_db)
        await db.commit()

    return event_db

@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db),
                    tenant_id: str = Depends(verify_api_key)):
    
    
    stmt = select(EventModel).where(EventModel.id == event_id)
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
