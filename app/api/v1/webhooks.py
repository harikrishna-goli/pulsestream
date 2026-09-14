import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.middleware.auth import verify_api_key
from app.database import get_db
from app.models.event import WebhookEndpointModel
from app.schemas.event import WebhookCreate, WebhookResponse

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook(wh_in: WebhookCreate, db: AsyncSession = Depends(get_db), 
                           tenant_id: str = Depends(verify_api_key)):
    
    wh_id = f"wh_{uuid.uuid4().hex[:12]}"
    wh_db = WebhookEndpointModel(
        id=wh_id,
        tenant_id=tenant_id,
        target_url=wh_in.target_url,
        secret=wh_in.secret or f"whsec_{uuid.uuid4().hex[:16]}"
    )
    db.add(wh_db)
    await db.commit()
    await db.refresh(wh_db)
    return wh_db

@router.get("", response_model=List[WebhookResponse])
async def list_webhooks(tenant_id: str= Depends(verify_api_key), 
                        db: AsyncSession = Depends(get_db)):
    
    stmt = select(WebhookEndpointModel).where(WebhookEndpointModel.tenant_id == tenant_id)
    res = await db.execute(stmt)
    return res.scalars().all()
