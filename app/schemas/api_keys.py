from pydantic import BaseModel, Field
from datetime import datetime

class APIKeyCreate(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_acme_corp"])
    name: str = Field(..., examples=["Production Ingestion Key"])

class APIKeyResponse(BaseModel):
    id: str
    tenant_id: str
    name: str = "Production Ingestion Key"
    raw_key: str
    key_prefix: str
    created_at: datetime

class APIKeyRevokeResponse(BaseModel):
    id: str
    tenant_id: str
    is_active: bool
    message: str

class APIKeySummary(BaseModel):
    id: str
    tenant_id: str
    key_prefix: str
    is_active: bool
    created_at: datetime