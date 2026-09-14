# 06. PulseStream Sprint 1 — Comprehensive Interview Questions & Scoring Rubric 🎙️
### Categorized SDE-2 & Senior Backend Engineering Defense Guide

This document catalogs every interview question that can be asked on **Sprint 1 (FastAPI Ingestion, API Key Authentication, PostgreSQL Async Architecture, and Test Engineering)**.

---

## 📊 Scoring Calibration System
Every answer is scored on a **1 to 10 Seniority Scale**:
* **1–4 (Junior / Naive)**: Answers with surface-level syntax, relies on tutorials, ignores concurrency, database failure modes, or security leaks.
* **5–7 (Mid-Level SDE-2)**: Knows the functional code, implements working endpoints, but misses driver lifecycle internals, data corruption risks, or distributed edge cases.
* **8–10 (Senior SDE / Staff Architect)**: Explains the architectural trade-offs, driver protocol mechanics, cryptographic invariants, race conditions, and production defense-in-depth.

---

## 📑 Topic Index
1. [Security, Cryptography & Multi-Tenant Authentication](#topic-1-security-cryptography--multi-tenant-authentication)
2. [Async Python, Event Loops & Database Driver Internals](#topic-2-async-python-event-loops--database-driver-internals)
3. [Database Transactions, Schema Invariants & Alembic Migrations](#topic-3-database-transactions-schema-invariants--alembic-migrations)
4. [Distributed API Design, Idempotency & Rate Limiting](#topic-4-distributed-api-design-idempotency--rate-limiting)
5. [Testing Strategy, Concurrency Fixtures & Test Isolation](#topic-5-testing-strategy-concurrency-fixtures--test-isolation)

---

## Topic 1: Security, Cryptography & Multi-Tenant Authentication

---

### Q1.1: "How did you design API Key authentication for PulseStream, and why can't you use bcrypt like passwords?"
* **Target Level**: L4 / L5 (Mid to Senior)
* **Core Competency**: Cryptographic Primitives, Ingestion Latency Trade-offs.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"We generate a random string, hash it, and check it in the database. We could use bcrypt or whatever password hashing library we like."* (Fails to understand CPU cost of bcrypt on high-throughput endpoints).
* **Mid-Level (5–7)**: *"We use `secrets.token_urlsafe(32)` for security and hash it with SHA-256 before saving to PostgreSQL. We return the raw key only once. We don't use bcrypt because bcrypt is intentionally slow."*
* **Senior (8–10)**: *"API key authentication operates on the critical data path of an event ingestion engine ($>1{,}000\text{ req/sec}$). Passwords use bcrypt or Argon2 because they deliberately incorporate key derivation work factors (e.g., $100\text{ms}$ hashing time) to defend low-entropy human passwords against offline brute-force attacks. API keys have 256 bits of high entropy from CSPRNG (`secrets.token_urlsafe(32)`), making brute-force mathematically impossible ($2^{256}$ space). Therefore, we use single-round SHA-256 which executes in $<1\mu\text{s}$, preventing our auth middleware from becoming a CPU bottleneck while ensuring that a leaked database dump never exposes usable credentials."*

---

### Q1.2: "When a customer revokes an API key, should you DELETE the row from Postgres? How did you design key revocation?"
* **Target Level**: L4 / L5 (Mid to Senior)
* **Core Competency**: Audit Trails, Referential Integrity, Tenant Isolation.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Yes, we run `DELETE FROM api_keys WHERE id = :key_id` so it is immediately gone."*
* **Mid-Level (5–7)**: *"No, we do a soft-delete by setting `is_active = False` so historical records aren't broken, and we filter `is_active == True` in the middleware."*
* **Senior (8–10)**: *"Hard deletion is an anti-pattern in event audit platforms. If you hard-delete an API key, foreign keys and immutable event ingestion ledgers lose their provenance—you can no longer audit which specific key ingested an event 6 months ago. Instead, we implement **stateful soft-deactivation** (`is_active = False` or `revoked_at = timestamp`). Furthermore, the revocation endpoint (`DELETE /api/v1/api-keys/{key_id}`) enforces strict tenancy scoping: the SQL query executes `WHERE id = :key_id AND tenant_id = :authenticated_tenant`. If Tenant B attempts to revoke Tenant A's key, it returns `404 Not Found` rather than `403 Forbidden` to prevent key enumeration attacks."*

---

## Topic 2: Async Python, Event Loops & Database Driver Internals

---

### Q2.1: "What causes `asyncpg.InterfaceError: cannot perform operation: another operation is in progress` in an async FastAPI application, and how do you prevent it?"
* **Target Level**: L5 / L6 (Senior to Staff)
* **Core Competency**: AsyncIO Event Loop Binding, Connection Pool Lifecycle.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"It means two queries were running at the same time, so we just need to add more await statements."*
* **Mid-Level (5–7)**: *"In `asyncpg`, a single connection can't handle multiple concurrent queries. It happens if you share the same `AsyncSession` across concurrent tasks without using separate sessions."*
* **Senior (8–10)**: *"This is a socket protocol state collision between `asyncpg` and the `asyncio` event loop. Unlike multi-threaded synchronous drivers that use thread-local state, `asyncpg` binds its raw TCP socket protocol directly to the specific active `asyncio` event loop that opened it. In test suites (or misconfigured middleware), `pytest-asyncio` creates and destroys a new event loop for each test by default. If SQLAlchemy's connection pool holds onto an open connection from a previous loop and hands it to a coroutine running on a new loop, `asyncpg` detects protocol mismatch and throws `another operation is in progress`. In production, this also happens if a coroutine times out or is cancelled mid-query while the socket is still reading bytes. The fix is threefold: (1) configure `asyncio_default_test_loop_scope = 'session'`, (2) call `await engine.dispose()` on teardown to purge stale sockets, and (3) ensure FastAPI's `Depends(get_db)` has request-scoped lifecycles."*

---

### Q2.2: "Why did `datetime.now(timezone.utc)` throw a `TypeError: can't subtract offset-naive and offset-aware datetimes` during database insertion into Postgres?"
* **Target Level**: L4 / L5 (Mid to Senior)
* **Core Competency**: PostgreSQL Wire Protocol, Type System Interoperability.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Python datetime had timezones, and Postgres didn't like it, so we stripped the timezone."*
* **Mid-Level (5–7)**: *"Postgres column was `TIMESTAMP WITHOUT TIME ZONE` (naive), but Python was creating aware datetimes with `timezone.utc`. SQLAlchemy/asyncpg can't subtract them."*
* **Senior (8–10)**: *"PostgreSQL has two distinct timestamp types: `TIMESTAMP` (naive, no timezone offset stored) and `TIMESTAMPTZ` (stored in UTC, displays in session timezone). SQLAlchemy's `Column(DateTime)` defaults to `TIMESTAMP WITHOUT TIME ZONE`. When `asyncpg` encodes a Python datetime into Postgres binary wire protocol for a naive column, it verifies that the Python object is also naive. If Python passes an offset-aware datetime (`tzinfo=UTC`), `asyncpg` attempts to calculate epoch delta by subtracting against a naive epoch, which causes Python's runtime to raise `TypeError: can't subtract offset-naive and offset-aware datetimes`. The production fix is either defining the schema explicitly as `DateTime(timezone=True)` (`TIMESTAMPTZ`), or standardizing internal Python defaults on UTC-naive instances using `.replace(tzinfo=None)`."*

---

## Topic 3: Database Transactions, Schema Invariants & Alembic Migrations

---

### Q3.1: "If you call `Base.metadata.drop_all()` in your test suite against PostgreSQL, does it affect Alembic? What breaks?"
* **Target Level**: L5 (Senior SDE)
* **Core Competency**: Migration State Machines, Schema Drift Detection.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Yes, it drops everything so Alembic will just re-run all migrations next time."*
* **Mid-Level (5–7)**: *"It drops the application tables, but it leaves the `alembic_version` table behind, which makes Alembic confused."*
* **Senior (8–10)**: *"It triggers a silent **Schema Desynchronization / Ghost State**. `Base.metadata.drop_all()` only drops tables registered in SQLAlchemy's `Base` registry (`events`, `api_keys`). It does NOT touch `alembic_version` because that table was created by Alembic's runtime, not your models. As a result, all business tables are obliterated, but `alembic_version` remains populated with revision hash `a1b2c3d (head)`. When your deployment pipeline runs `alembic upgrade head`, Alembic reads `alembic_version`, assumes the database is up-to-date, and applies 0 migrations—causing immediate runtime crashes (`relation "events" does not exist`). This is why tests must never share a database with Alembic-managed environments; tests should run against an isolated ephemeral database (`pulsestream_test`) or SQLite."*

---

### Q3.2: "How do you achieve zero-data-loss isolation in test suites without dropping tables between test runs?"
* **Target Level**: L5 (Senior SDE)
* **Core Competency**: ACID Savepoints, Database Test Performance.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Delete all rows using `DELETE FROM table;` after every test."*
* **Mid-Level (5–7)**: *"Run `drop_all` and `create_all` in an autouse fixture."*
* **Senior (8–10)**: *"Dropping and recreating tables in Postgres incurs massive DDL catalog locking and slows test execution from milliseconds to seconds. The senior pattern is **Nested Transaction Rollback (Savepoints)**: (1) Run DDL/migrations once at the start of the test session. (2) For each test, open an outer transaction on a dedicated connection. (3) Bind the FastAPI `AsyncSession` to this transaction. (4) At test completion, immediately call `await transaction.rollback()`. Because the rollback is executed at the database transaction layer, zero test rows are ever written to disk, and tests execute at pure in-memory speeds with 100% isolation."*

---

## Topic 4: Distributed API Design, Idempotency & Rate Limiting

---

### Q4.1: "Why is an `Idempotency-Key` required in an event ingestion API, and how do you prevent race conditions when two identical requests arrive simultaneously?"
* **Target Level**: L5 / L6 (Senior to Staff)
* **Core Competency**: Distributed Consensus, Network Partitions, Concurrency Invariants.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"To make sure duplicate events aren't saved. We check if the key is in the database, and if not, we insert it."*
* **Mid-Level (5–7)**: *"Clients can retry due to network drops. If we already processed the key, we return the cached response. We use a unique constraint on `idempotency_key`."*
* **Senior (8–10)**: *"In distributed networks, network timeouts are ambiguous (the two generals' problem): the client doesn't know if the request failed before reaching the server, while processing, or while returning the response. Clients must retry aggressively with an `Idempotency-Key`. To prevent concurrent race conditions (two identical requests arriving at the exact same millisecond across two API workers):
1. A naive 'check-then-insert' has a Time-of-Check to Time-of-Use (TOCTOU) race condition.
2. We enforce a database-level `UNIQUE` index on `(tenant_id, idempotency_key)`.
3. In high-scale architectures, we use an atomic Redis lock: `SET idempotency:{tenant}:{key} IN_PROGRESS NX EX 120`. If the lock fails, the second request polls or waits. Once the transaction commits, we cache the serialized HTTP response body and status code for 24 hours."*

---

### Q4.2: "Why did you replace `@app.on_event('startup')` with `lifespan` in FastAPI?"
* **Target Level**: L4 / L5 (Mid-Level)
* **Core Competency**: Modern ASGI Lifecycle, Resource Cleanup Invariants.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Because FastAPI showed a deprecation warning in the terminal."*
* **Mid-Level (5–7)**: *"FastAPI deprecated `on_event` in favor of `@asynccontextmanager async def lifespan(app: FastAPI)` which combines startup and shutdown in one function."*
* **Senior (8–10)**: *"`on_event('startup')` and `on_event('shutdown')` were decoupled, error-prone event hooks that lacked shared context and didn't conform to the ASGI standard specification. With Python's `asynccontextmanager` `lifespan`, startup code runs before `yield` and shutdown/cleanup code runs in the `finally` block after `yield`. This ensures that resources initialized on startup (like database connection pools, Redis clients, or HTTP client sessions) share the same execution context and are guaranteed to execute cleanup even if an unhandled exception or SIGTERM occurs during shutdown."*

---

## Topic 5: Testing Strategy, Concurrency Fixtures & Test Isolation

---

### Q5.1: "Why did your test suite use `httpx.AsyncClient(transport=ASGITransport(app=app))` instead of FastAPI's standard `TestClient`?"
* **Target Level**: L4 / L5 (Mid to Senior)
* **Core Competency**: ASGI Protocol, Event Loop Concurrency, Threading Boundaries.

#### 🎯 Evaluation Rubric
* **Junior (1–4)**: *"Because our API endpoints are async, so we needed an async client."*
* **Mid-Level (5–7)**: *"FastAPI's standard `TestClient` is synchronous and built on `requests`. It runs in a separate thread and can cause issues with async database sessions."*
* **Senior (8–10)**: *"FastAPI's built-in `TestClient` is synchronous (wrapping Starlette and `requests`). When testing an async codebase that utilizes `asyncpg` and `AsyncSession`, `TestClient` manages its own internal event loop in a background thread. This thread boundary breaks async fixtures that share database transactions or async mocks across the test and the endpoint. By using `httpx.AsyncClient` with `ASGITransport(app=app)`, HTTP calls are dispatched directly into the FastAPI ASGI callable on the **exact same `asyncio` event loop**, eliminating thread switching, preventing deadlocks, and allowing true end-to-end asynchronous testing."*

---

## 🏆 SDE-2 Interview Prep Summary Card

| Topic | Key Metric / Invariant to Mention |
| :--- | :--- |
| **Auth Cryptography** | SHA-256 single-round ($<1\mu\text{s}$) over CSPRNG 256-bit token; avoids bcrypt CPU exhaustion on $1{,}000\text{ req/s}$. |
| **Revocation** | Soft-deactivation (`is_active = False`) maintains referential integrity and historical audit trails. |
| **Database Driver** | `asyncpg` binds to active `asyncio` loop; session loop scope and `engine.dispose()` prevent `InterfaceError`. |
| **Timestamp Wire Protocol** | UTC-naive timestamps match PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` without offset subtraction crashes. |
| **Alembic Invariant** | `drop_all` skips `alembic_version`, creating schema desynchronization; tests must run on isolated test DBs. |
| **API Idempotency** | At-most-once delivery via `UNIQUE` constraints and atomic state locks to solve network timeout ambiguity. |
