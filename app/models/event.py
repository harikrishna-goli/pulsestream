import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Boolean, ForeignKey
from ..database import Base

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

class EventModel(Base):
    __tablename__ = "events"
    
    id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    event_type = Column(String(128), index=True, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class WebhookEndpointModel(Base):
    __tablename__ = "webhook_endpoints"
    
    id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    target_url = Column(String(512), nullable=False)
    secret = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    
    key = Column(String(128), primary_key=True, index=True)
    response_code = Column(Integer, nullable=False)
    response_body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    
    id = Column(String(64), primary_key=True)
    event_id = Column(String(64), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    destination_url = Column(String(512), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), default="PENDING", nullable=False, index=True)  # PENDING, IN_FLIGHT, DELIVERED, FAILED
    attempt_count = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class DeadLetterQueueModel(Base):
    __tablename__ = "dead_letter_queue"
    
    id = Column(String(64), primary_key=True)
    outbox_id = Column(String(64), nullable=False, index=True)
    event_id = Column(String(64), nullable=False, index=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    destination_url = Column(String(512), nullable=False)
    payload = Column(JSON, nullable=False)
    failure_reason = Column(Text, nullable=False)
    last_response_code = Column(Integer, nullable=True)
    failed_at = Column(DateTime, default=utc_now, nullable=False)

 