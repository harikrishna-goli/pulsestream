import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict

class EventCreate(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_acme_corp"])
    event_type: str = Field(..., examples=["order.payment_completed"])
    payload: Dict[str, Any] = Field(..., examples=[{"order_id": "ord_123", "amount": 99.50, "currency": "USD"}])

class EventResponse(BaseModel):
    id: str
    tenant_id: str
    event_type: str
    payload: Dict[str, Any]
    status: str
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

class WebhookCreate(BaseModel):
    tenant_id: str
    target_url: str
    secret: Optional[str] = "whsec_default_secret"

class WebhookResponse(BaseModel):
    id: str
    tenant_id: str
    target_url: str
    is_active: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
