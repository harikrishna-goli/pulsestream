# PulseStream

An async event ingestion and webhook delivery service built with FastAPI, PostgreSQL, and Redis.

## Why I built this

When services emit events (payments, order updates, signups) and push them to customer webhook URLs, two things usually go wrong:
- Slow or down customer servers block the sender or drop events.
- Network timeouts cause clients to retry, which creates duplicate events and duplicate webhook deliveries.

PulseStream sits in between as an async buffer: it accepts events quickly, deduplicates retries over a 24-hour window, enforces per-tenant rate limits, and dispatches signed webhooks in the background with retries and a Dead Letter Queue (DLQ).

---

## What it does

- **Event Ingestion (`POST /api/v1/events`)**: Validates and stores incoming JSON events with a unique `evt_...` ID, then queues webhook deliveries in the background.
- **24-Hour Idempotency (`Idempotency-Key`)**: Checks Redis first (`SETEX` 24h) and falls back to PostgreSQL (`expires_at`) so retried requests return the original response without duplicating records or re-firing webhooks.
- **Distributed Rate Limiting**: Uses a Redis Lua token-bucket script (`EVALSHA`) keyed by hashed `X-API-Key` (or client IP) with fail-open fallback if Redis is unreachable.
- **Tenant & API Key Management**: Supports `/api/v1/users/register`, `/api/v1/users/me`, `/api/v1/users/delete`, and `/api/v1/api-keys/` with `ps_alive_...` keys stored as SHA-256 hashes.
- **Webhook Dispatch & Retries (`POST /api/v1/webhooks`)**: Signs outgoing payloads with `X-PulseStream-Signature: sha256=<hmac>`. On `5xx` or timeouts, retries up to 5 times with exponential backoff and jitter before moving failed deliveries to `dead_letter_queue`.
- **Health & Metrics**: Exposes `/healthz` (liveness), `/readyz` (PostgreSQL + Redis check), and `/metrics` (Prometheus).

---

## Stack

- **API**: Python 3.14, FastAPI, Uvicorn
- **Database**: PostgreSQL via SQLAlchemy 2.0 (`asyncpg`) + Alembic
- **Cache / Rate Limiter**: Redis (`redis.asyncio` + Lua token bucket)
- **HTTP Client**: `httpx`
- **Testing**: `pytest`, `pytest-asyncio`

---

## API Flow

1. **Create an API key**
   ```bash
   curl -X POST https://pulsestream-fjui.onrender.com/api/v1/users/register \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": "tenant_acme"}'
   ```

2. **Register a webhook**
   ```bash
   curl -X POST https://pulsestream-fjui.onrender.com/api/v1/webhooks \
     -H "Content-Type: application/json" \
     -H "X-API-Key: ps_alive_YOUR_KEY" \
     -d '{"tenant_id": "tenant_acme", "target_url": "https://webhook.site/your-id", "secret": "whsec_demo"}'
   ```

3. **Ingest an event (with idempotency)**
   ```bash
   curl -X POST https://pulsestream-fjui.onrender.com/api/v1/events \
     -H "Content-Type: application/json" \
     -H "X-API-Key: ps_alive_YOUR_KEY" \
     -H "Idempotency-Key: order-1001" \
     -d '{"tenant_id": "tenant_acme", "event_type": "order.paid", "payload": {"amount": 99.5, "currency": "USD"}}'
   ```

4. **Check docs & health**
   - Swagger UI: `/docs`
   - Liveness: `/healthz`
   - Readiness: `/readyz`
   - Metrics: `/metrics`

---

## Running Locally

### With Docker Compose
```bash
docker-compose up --build
```

### With a local virtual environment
1. Copy `.env.example` to `.env` and set `DATABASE_URL` and `REDIS_URL`.
2. Install dependencies and run migrations:
   ```bash
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```

### Run tests
```bash
pytest --verbose
```

---

## Deployment & Infrastructure (Free Tier)

PulseStream is deployed across three free managed services configured via [`render.yaml`](render.yaml):

| Layer | Service | Why & How We Use It |
| :--- | :--- | :--- |
| **Application** | **Render** (Web Service) | Runs the FastAPI/Uvicorn server (`https://pulsestream-fjui.onrender.com`) with auto-deploy from `main`. |
| **Database** | **Neon** (PostgreSQL) | Stores events, API keys, webhooks, 24h idempotency records, and the Dead Letter Queue (`dead_letter_queue`). |
| **Cache & Rate Limiter** | **Upstash** (Redis) | Powers the distributed Lua token-bucket rate limiter (`ratelimit:*`) and fast 24h idempotency cache (`idem:*`). |

### Build & Startup Process (Render)

1. **Build**: Render installs dependencies via `pip install -r requirements.txt` (including `sqlalchemy[asyncio]`/`greenlet` and `asyncpg`).
2. **Start**: Runs `uvicorn app.main:app --host 0.0.0.0 --port 10000`.
3. **Startup Lifespan**: Automatically creates missing tables (`Base.metadata.create_all`) and ensures `idempotency_records.expires_at` exists without dropping existing data.
4. **Health Check**: Render polls `/healthz` (lightweight liveness check without DB/Redis I/O so Neon can auto-pause normally).

### Service Configuration Details

- **Neon (PostgreSQL)**
  - Use the **`asyncpg`** driver prefix and TLS query param:
    ```text
    postgresql+asyncpg://<user>:<password>@<neon-host>/<db>?ssl=true
    ```
  - Drop `?sslmode=require&channel_binding=require` (psycopg2 syntax) — `asyncpg` expects `?ssl=true`.
  - Neon's free tier auto-pauses after 5 minutes of inactivity, so [`app/database.py`](app/database.py) sets `pool_pre_ping=True` and `pool_recycle=300` to automatically recover from closed idle connections.

- **Upstash (Redis)**
  - Use the **TLS/SSL TCP endpoint** (`rediss://...`, not the REST URL):
    ```text
    rediss://default:<password>@<upstash-host>:6379
    ```
  - [`app/services/redis.py`](app/services/redis.py) sets `ssl_cert_reqs=None` for `rediss://` connections so managed TLS certs connect cleanly while keeping traffic encrypted.
  - Configured with `RATE_LIMIT_FAIL_OPEN=true` and `REDIS_TIMEOUT_SECONDS=0.5`, so if Upstash's free 10,000 commands/day limit is reached or Redis times out, requests continue flowing without downtime.

- **Render Environment Variables**
  Set these in **Render Dashboard → Environment** (never commit secrets to git):
  - `DATABASE_URL` — Neon `postgresql+asyncpg://...?ssl=true` string
  - `REDIS_URL` — Upstash `rediss://...` string
  - `WEBHOOK_SECRET_KEY` — Auto-generated HMAC signing secret
  - `RATE_LIMIT_PER_MINUTE` — `60`
  - `RATE_LIMIT_FAIL_OPEN` — `true`
  - `REDIS_TIMEOUT_SECONDS` — `0.5`
