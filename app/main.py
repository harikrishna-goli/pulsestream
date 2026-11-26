"""
Understanding the User Persona & Core Problem Statement:
### The Problem
Modern distributed applications (e.g. Stripe, Shopify, GitHub) generate millions of asynchronous events (payments completed, invoices generated, orders shipped).
Third-party customer servers are often slow, crash unpredictably, or fail to respond.
- If the sender sends synchronously, customer downtime will block or crash the sender's servers.
- If network requests time out and the sender retries, customers may get charged twice or process duplicate orders.

### The Solution: PulseStream
PulseStream acts as a bulletproof, high-throughput buffer:
1. Ingests events asynchronously at microsecond speed with atomic Idempotency (zero duplicate processing).
2. Protects downstream systems using Distributed Token-Bucket Rate Limiting.
3. Dispatches webhooks to customer endpoints with HMAC-SHA256 signatures, exponential backoff retries, and a Dead Letter Queue (DLQ) for unrecoverable failures.

Functional Requirements:
FR-1: High-Throughput Event Ingestion (POST /api/v1/events):
  - Ingest JSON events with a tenant identifier, event type, and arbitrary JSON payload.
  - Return HTTP `201 Created` immediately with an assigned unique event ID (`evt_xxxx`).
FR-2: Atomic Idempotency (`Idempotency-Key` Header):
  - If a client retries a request with the same `Idempotency-Key` within a 24-hour window, the API must return the cached original response without creating duplicate database records or re-triggering webhook dispatches.
FR-3: Webhook Endpoint Management (`POST /api/v1/webhooks`):
  - Allow tenants to register target URLs and optional signing secrets.
FR-4: Asynchronous Reliable Dispatching:
  - Whenever an event is ingested, dispatch a `POST` request to all active webhook endpoints subscribed to that tenant.
  - Sign the payload using `HMAC-SHA256` in the header: `X-PulseStream-Signature: sha256=<hash>`.
FR-5: Exponential Backoff & Dead Letter Queue (DLQ):
  - If a customer endpoint returns `5xx` or times out, retry up to 5 times with exponential backoff and randomized jitter.
  - If all 5 attempts fail, move the payload to a persistent **Dead Letter Queue (DLQ)**.
FR-6: Observability & Health Probing:
  - Expose `/healthz` (liveness), `/readyz` (readiness), and `/metrics` (Prometheus exposition).
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import settings
from .database import engine, Base
from .middleware.rate_limiter import RedisTokenBucketRateLimiter
from .api.v1.events import router as events_router
from .api.v1.webhooks import router as webhooks_router
from .api.v1.health import router as health_router
from .api.v1.api_keys import router as security_router
from .api.v1.users import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="PulseStream",
        description="High-Throughput Distributed Event Ingestion & Webhook Dispatcher Engine",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )

    # Middleware
    app.add_middleware(RedisTokenBucketRateLimiter, rate_limit=settings.RATE_LIMIT_PER_MINUTE)

    # Routers
    app.include_router(events_router, prefix=settings.API_V1_PREFIX)
    app.include_router(webhooks_router, prefix=settings.API_V1_PREFIX)
    app.include_router(health_router)
    app.include_router(security_router, prefix=settings.API_V1_PREFIX)
    app.include_router(users_router, prefix=settings.API_V1_PREFIX)

    return app

app = create_app()
