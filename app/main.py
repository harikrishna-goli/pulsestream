from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import settings
from .database import engine, Base
from .middleware.rate_limiter import InMemoryTokenBucketRateLimiter
from .api.v1.events import router as events_router
from .api.v1.webhooks import router as webhooks_router
from .api.v1.health import router as health_router
from .api.v1.api_keys import router as security_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="PulseStream API",
        description="High-Throughput Distributed Event Ingestion & Webhook Dispatcher Engine",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )

    # Middleware
    app.add_middleware(InMemoryTokenBucketRateLimiter, rate_limit=settings.RATE_LIMIT_PER_MINUTE)

    # Routers
    app.include_router(events_router, prefix=settings.API_V1_PREFIX)
    app.include_router(webhooks_router, prefix=settings.API_V1_PREFIX)
    app.include_router(health_router)
    app.include_router(security_router, prefix=settings.API_V1_PREFIX)

    return app

app = create_app()
