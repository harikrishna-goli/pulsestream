# Sprint Milestones & Hands-on Implementation Tasks 🚀
### PulseStream: Step-by-Step 4-Week Developer Backlog

---

## 📅 Sprint Overview & Progress Tracker

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Sprint 1 (Week 1): Database Modeling, Alembic & API Key Authentication     │
│  Sprint 2 (Week 2): Distributed Concurrency (Redis Lua Rate Limiter & Idem) │
│  Sprint 3 (Week 3): Transactional Outbox Pipeline, Retries & Dead Letter Q  │
│  Sprint 4 (Week 4): Locust Load Testing (1,000 req/s), Metrics & CI/CD      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🏃 Sprint 1 (Week 1): Database Modeling, Alembic & Security

### Goal: Replace mock DB with PostgreSQL Asyncpg, Alembic migrations, and API Key Auth.

- [x] **Task 1.1: Configure Async Database Engine**
  - *Location*: `app/database.py`
  - *Action*: Configure async connection pooling (`pool_size=20`, `max_overflow=10`, `pool_recycle=3600`).
  - *Acceptance Criteria*: Database connections properly reuse existing pools under high concurrency without leaking.
- [x] **Task 1.2: Initialize Alembic Migrations**
  - *Location*: `alembic/`
  - *Action*: Run `alembic init -t async alembic`, wire `target_metadata = Base.metadata` in `env.py`.
  - *Acceptance Criteria*: Running `alembic revision --autogenerate -m "initial_tables"` produces clean migration files for `events`, `webhook_endpoints`, `outbox_events`, and `dead_letter_queue`.
- [x] **Task 1.3: Build API Key Authentication Dependency**
  - *Location*: `app/middleware/auth.py`
  - *Action*: Create `verify_api_key` dependency using `Security(APIKeyHeader(name="X-API-Key"))`. Store SHA-256 salted hashes in DB.
  - *Acceptance Criteria*: Unauthenticated requests return `401 Unauthorized`. Valid keys populate `request.state.tenant_id`.

---

## 🏃 Sprint 2 (Week 2): Distributed Concurrency & Idempotency

### Goal: Guarantee atomic deduplication and distributed rate limiting across multiple server nodes.

- [ ] **Task 2.1: Write Redis Lua Token-Bucket Rate Limiter**
  - *Location*: `app/middleware/rate_limiter.py`
  - *Action*: Replace `defaultdict` with atomic Redis Lua script (`evalsha` execution).
  - *Acceptance Criteria*: When a tenant exceeds their limit, return HTTP `429 Too Many Requests` with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` headers.
- [ ] **Task 2.2: Implement Distributed Idempotency Key Filter**
  - *Location*: `app/middleware/idempotency.py`
  - *Action*: Use Redis `SET "idem:{key}" "IN_FLIGHT" NX EX 120` to acquire a lock. Save cached response upon transaction commit with 24-hour TTL.
  - *Acceptance Criteria*: Sending 50 identical concurrent requests with the same `Idempotency-Key` results in exactly 1 database write and 49 identical cached responses.

---

## 🏃 Sprint 3 (Week 3): Transactional Outbox & Resilient Webhook Worker

### Goal: Eliminate data loss on server crashes with background worker retry loops.

- [ ] **Task 3.1: Implement Transactional Outbox Writer**
  - *Location*: `app/api/v1/events.py`
  - *Action*: In the same ACID transaction as `EventModel`, write corresponding dispatch entries into `OutboxModel`.
  - *Acceptance Criteria*: Even if the server process terminates immediately after HTTP 201, the outbox record persists in PostgreSQL.
- [ ] **Task 3.2: Build Asynchronous Webhook Dispatcher Worker**
  - *Location*: `app/services/worker.py`
  - *Action*: Create a background worker loop using `SELECT ... FOR UPDATE SKIP LOCKED` to safely claim pending outbox events across multiple parallel workers.
  - *Acceptance Criteria*: Parallel workers never double-dispatch the same outbox item.
- [ ] **Task 3.3: Implement Exponential Backoff with Jitter & Dead Letter Queue (DLQ)**
  - *Location*: `app/services/webhook_dispatcher.py`
  - *Action*: Retry on `5xx` / timeouts up to 5 times. On 5th failure, move payload to `dead_letter_queue` with failure reason.
  - *Acceptance Criteria*: Failed events move to DLQ without blocking other tenant deliveries. Provide `POST /api/v1/webhooks/dlq/replay` endpoint.

---

## 🏃 Sprint 4 (Week 4): Load Testing, Observability & Cloud CI/CD

### Goal: Benchmark to 1,000+ req/sec, instrument Prometheus, and deploy live.

- [ ] **Task 4.1: Write Locust Load Testing Script**
  - *Location*: `tests/load/locustfile.py`
  - *Action*: Simulate 200 concurrent clients generating $1{,}000+\text{ req/sec}$.
  - *Acceptance Criteria*: p95 latency stays under $15\text{ms}$ with zero 500 errors.
- [ ] **Task 4.2: Instrument Prometheus Metrics**
  - *Location*: `app/api/v1/health.py`
  - *Action*: Expose custom metrics: `pulsestream_events_total`, `pulsestream_webhook_duration_seconds`, `pulsestream_dlq_count`.
  - *Acceptance Criteria*: Prometheus `/metrics` endpoint exports valid OpenMetrics format.
- [ ] **Task 4.3: GitHub Actions CI/CD & Cloud Deployment**
  - *Location*: `.github/workflows/ci.yml`
  - *Action*: Configure automated linting (`ruff`), type checking (`mypy --strict`), test coverage (`pytest --cov=app --cov-fail-under=85`), and container push.
  - *Acceptance Criteria*: Every pull request passes CI checks automatically. Deploy container live to AWS ECS or Render.
