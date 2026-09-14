import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from ..database import Base

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

class APIKeyModel(Base):
    __tablename__ = "api_keys"
    
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    key_hash = Column(String(128), unique=True, index=True, nullable=False)
    key_prefix = Column(String(15), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)