# RailReserve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized railway seat-booking demo that reproduces double booking in naive mode and proves exactly-one-winner allocation, idempotent payment, hold expiry, and API-node failover in safe mode.

**Architecture:** Two FastAPI replicas behind Nginx, with Postgres as the authoritative inventory and Redis for non-authoritative rate limiting. Seat holds use a conditional row update; payment confirmation is one transaction guarded by an idempotency key. A separate naive path and a `naive_bookings` table make the race observable without weakening the safe schema.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, Postgres 16, Redis 7, Nginx 1.27, Docker Compose, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-10-20-irctc-double-booking-demo-design.md`

## Global Constraints

- All application code lives under `railreserve/` in this workspace.
- Python 3.12 in Docker; do not depend on host Python packages.
- Postgres 16 is the only authoritative store; Redis is optional for correctness.
- Two API replicas (`api1`, `api2`) must run behind Nginx at `http://localhost:8080`.
- Demo defaults: `train_id=12951`, `journey_date=2026-11-01`, 50 seats named `S1-01` through `S1-50`.
- Hold TTL is 300 seconds by default; the Compose demo stack overrides it to 10 seconds.
- Naive-mode delay is 150 ms by default; the Compose demo stack overrides it to 300 ms for a reliable on-stage race.
- Redis rate limiting is fail-open and never part of booking correctness.
- All timestamps are stored and compared in UTC using `TIMESTAMPTZ`; journey dates are `DATE`.
- Safe-mode invariants: one active hold per seat, one booking per seat, one payment per idempotency key.
- No real authentication, real payment gateway, cancellation, waitlist, or RAC.
- Do not commit to git unless the user explicitly asks; this workspace is not currently a git repository.
- Public IRCTC facts and the proposed architecture must remain labeled separately in slides.

## Review Focus

1. Concurrent holds for the same seat must yield exactly one active hold and no duplicate seat allocation; covered by Task 6.
2. Replayed payment callbacks must return the original booking and never create a second payment; covered by Task 4.
3. An expired hold must not be payable, and its seat must become holdable again; covered by Tasks 3 and 4.
4. A stopped API replica must not block bookings through Nginx; covered by Task 7 verification.
5. Naive mode must reliably produce multiple winners during the live demo without weakening the safe path; covered by Tasks 5 and 8.

---

### Task 1: Project scaffold, health endpoint, and base Compose stack

**Files:**
- Create: `railreserve/requirements.txt`
- Create: `railreserve/Dockerfile`
- Create: `railreserve/.dockerignore`
- Create: `railreserve/app/__init__.py`
- Create: `railreserve/app/main.py`
- Create: `railreserve/tests/test_health.py`
- Create: `railreserve/scripts/.gitkeep`
- Create: `railreserve/db/init.sql` (minimal placeholder; replaced in Task 2)
- Create: `railreserve/docker-compose.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.main.app` (FastAPI instance) with `GET /health -> {"status": "ok"}`; Compose services `postgres`, `redis`, `api1`, `api2`.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd railreserve && docker compose build api1 && docker compose run --rm --no-deps api1 pytest tests/test_health.py -v`

Expected: FAIL because `app.main` or `/health` does not exist.

- [ ] **Step 3: Add the scaffold**

`requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
psycopg[binary,pool]==3.2.3
redis==5.2.1
httpx==0.28.1
pytest==8.3.4
```

`Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY db ./db
COPY tests ./tests
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="RailReserve")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

`db/init.sql` placeholder:

```sql
SELECT 1;
```

`docker-compose.yml` must define `postgres`, `redis`, `api1`, and `api2`. Postgres uses `postgres:16-alpine` with user/password/database `rail`/`rail`/`railreserve`, and mounts `./db/init.sql` into `/docker-entrypoint-initdb.d/`. Redis uses `redis:7-alpine`. Each API service builds the local Dockerfile, sets `DATABASE_URL=postgresql://rail:rail@postgres:5432/railreserve`, `REDIS_URL=redis://redis:6379/0`, `HOLD_TTL_SECONDS=10`, `NAIVE_DELAY_MS=300`, and depends on Postgres being healthy and Redis being started.

- [ ] **Step 4: Run the health test to verify it passes**

Run: `cd railreserve && docker compose build api1 && docker compose run --rm --no-deps api1 pytest tests/test_health.py -v`

Expected: PASS.

- [ ] **Step 5: Validate the Compose file**

Run: `cd railreserve && docker compose config`

Expected: exit code 0 and a rendered configuration with four services.

No git commit is performed.

---

### Task 2: Schema, connection pool, reset, and seat listing

**Files:**
- Modify: `railreserve/db/init.sql`
- Create: `railreserve/app/config.py`
- Create: `railreserve/app/db.py`
- Create: `railreserve/app/repository.py`
- Create: `railreserve/app/schemas.py`
- Modify: `railreserve/app/main.py`
- Create: `railreserve/tests/conftest.py`
- Create: `railreserve/tests/test_repository.py`

**Interfaces:**
- Consumes: Compose Postgres service from Task 1.
- Produces:
  - `config.get_settings() -> Settings` with `database_url`, `redis_url`, `hold_ttl_seconds`, `naive_delay_ms`, `sweeper_enabled`, `sweeper_interval_seconds`.
  - `db.init_pool(url: str, max_size: int = 20) -> None`, `db.get_pool() -> ConnectionPool`, `db.close_pool() -> None`.
  - `repository.reset_demo(conn, train_id: str, journey_date: date, seat_count: int) -> list[dict]`.
  - `repository.list_seats(conn, train_id: str, journey_date: date) -> list[dict]`.
  - `schemas.ResetRequest(train_id: str, journey_date: date, seat_count: int)`.
  - `POST /api/demo/reset` and `GET /api/seats` endpoints.

- [ ] **Step 1: Write the failing repository tests**

`tests/conftest.py` must create a `railreserve_test` database, apply `db/init.sql`, initialize the pool, and truncate tables between tests. Use these environment defaults:

```python
TEST_ADMIN_URL = "postgresql://rail:rail@postgres:5432/postgres"
TEST_DATABASE_URL = "postgresql://rail:rail@postgres:5432/railreserve_test"
```

The schema is applied by reading `db/init.sql` and executing each non-empty statement split on `;`. Set `DATABASE_URL=TEST_DATABASE_URL`, `SWEEPER_ENABLED=false`, and `RATE_LIMIT_PER_MINUTE=0` before importing the app.

`tests/test_repository.py`:

```python
from datetime import date

from app import db, repository


def test_reset_demo_seeds_requested_seats():
    with db.get_pool().connection() as conn:
        seats = repository.reset_demo(conn, "12951", date(2026, 11, 1), 5)
        conn.commit()
        rows = repository.list_seats(conn, "12951", date(2026, 11, 1))
    assert len(seats) == 5
    assert [row["seat_no"] for row in rows] == [f"S1-{i:02d}" for i in range(1, 6)]
    assert {row["status"] for row in rows} == {"available"}


def test_reset_demo_clears_previous_state():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, "12951", date(2026, 11, 1), 2)
        conn.commit()
        repository.reset_demo(conn, "12951", date(2026, 11, 1), 3)
        conn.commit()
        rows = repository.list_seats(conn, "12951", date(2026, 11, 1))
    assert len(rows) == 3
    assert [row["id"] for row in rows] == [1, 2, 3]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_repository.py -v`

Expected: FAIL because `config`, `db`, `repository`, and the schema do not exist.

- [ ] **Step 3: Implement the schema, pool, repository, and endpoints**

`db/init.sql` must contain the exact tables and sequence from the spec: `seats`, `holds` (with partial unique index `one_active_hold_per_seat`), `bookings`, `payments`, `naive_bookings`, and `pnr_seq`.

`app/config.py`:

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    hold_ttl_seconds: int
    naive_delay_ms: int
    sweeper_enabled: bool
    sweeper_interval_seconds: float


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://rail:rail@postgres:5432/railreserve"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        hold_ttl_seconds=int(os.getenv("HOLD_TTL_SECONDS", "300")),
        naive_delay_ms=int(os.getenv("NAIVE_DELAY_MS", "150")),
        sweeper_enabled=os.getenv("SWEEPER_ENABLED", "true").lower() == "true",
        sweeper_interval_seconds=float(os.getenv("SWEEPER_INTERVAL_SECONDS", "2")),
    )
```

`app/db.py` keeps one module-level `ConnectionPool`. `init_pool` closes an existing pool before replacing it, opens with `min_size=1`, `max_size=max_size`, and `kwargs={"row_factory": dict_row}`.

`repository.reset_demo` truncates in this order and reseeds:

```sql
TRUNCATE naive_bookings, payments, bookings, holds, seats RESTART IDENTITY CASCADE;
ALTER SEQUENCE pnr_seq RESTART WITH 1000000000;
```

Then it inserts `seat_count` rows for the given train/date with seat numbers `S1-01`, `S1-02`, and so on.

`repository.list_seats` returns `id`, `seat_no`, and `status`, ordered by `seat_no`.

`app/main.py` adds a lifespan that calls `db.init_pool(settings.database_url)` on startup and `db.close_pool()` on shutdown, plus the two endpoints. `POST /api/demo/reset` accepts `train_id`, `journey_date`, and `seat_count` (default 50) and returns `{"seats": [...]}`. `GET /api/seats` accepts query parameters `train_id` and `journey_date` and returns `{"seats": [...]}`. API tests create `TestClient(app)` without a context manager so the lifespan does not replace the test pool initialized by `conftest.py`.

- [ ] **Step 4: Run the repository tests to verify they pass**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_repository.py -v`

Expected: PASS (2 tests).

No git commit is performed.

---

### Task 3: Safe seat hold, expiry sweeper, and hold endpoint

**Files:**
- Create: `railreserve/app/errors.py`
- Create: `railreserve/app/service.py`
- Create: `railreserve/app/ratelimit.py`
- Modify: `railreserve/app/repository.py`
- Modify: `railreserve/app/schemas.py`
- Modify: `railreserve/app/main.py`
- Create: `railreserve/tests/test_hold.py`
- Create: `railreserve/tests/test_ratelimit.py`

**Interfaces:**
- Consumes: `db.get_pool`, `repository.reset_demo`, `repository.list_seats`.
- Produces:
  - `errors.SeatUnavailable`, `errors.HoldNotFound`, `errors.HoldExpired`, `errors.IdempotencyKeyReused`.
  - `repository.expire_stale(conn) -> None`.
  - `repository.hold_seat(conn, train_id: str, journey_date: date, seat_no: str, user_id: str, ttl_seconds: int) -> dict | None`.
  - `service.hold_seat(train_id, journey_date, seat_no, user_id) -> dict`.
  - `ratelimit.allow_hold(client, user_id: str, limit: int, window_seconds: int = 60) -> bool`.
  - `Settings.rate_limit_per_minute`.
  - `schemas.HoldRequest(train_id: str, journey_date: date, seat_no: str, user_id: str)`.
  - `POST /api/bookings/hold -> 201` (429 when rate-limited).

- [ ] **Step 1: Write the failing hold tests**

```python
from datetime import date

import pytest

from app import db, repository, service
from app.errors import SeatUnavailable

TRAIN = "12951"
DAY = date(2026, 11, 1)


def seed_one_seat():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()


def test_hold_seat_marks_seat_held():
    seed_one_seat()
    result = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    assert result["seat_no"] == "S1-01"
    with db.get_pool().connection() as conn:
        seat = repository.list_seats(conn, TRAIN, DAY)[0]
    assert seat["status"] == "held"


def test_second_hold_for_same_seat_is_rejected():
    seed_one_seat()
    service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    with pytest.raises(SeatUnavailable):
        service.hold_seat(TRAIN, DAY, "S1-01", "u2")


def test_expired_hold_can_be_reclaimed():
    seed_one_seat()
    first = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s",
            (first["hold_id"],),
        )
        conn.execute(
            "UPDATE seats SET hold_expires_at = now() - interval '1 second' WHERE id = %s",
            (first["seat_id"],),
        )
        conn.commit()
    second = service.hold_seat(TRAIN, DAY, "S1-01", "u2")
    assert second["seat_id"] == first["seat_id"]
    assert second["hold_id"] != first["hold_id"]
```

`tests/test_ratelimit.py`:

```python
from app.ratelimit import allow_hold


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True


def test_rate_limit_allows_within_limit_and_blocks_after():
    client = FakeRedis()
    assert allow_hold(client, "u1", 2) is True
    assert allow_hold(client, "u1", 2) is True
    assert allow_hold(client, "u1", 2) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_hold.py -v`

Expected: FAIL because `service`, the error types, and the hold repository function do not exist.

- [ ] **Step 3: Implement the hold flow**

`repository.hold_seat` runs one transaction:

1. Mark expired active holds for this seat as `expired`.
2. Run the conditional seat update from the spec:

```sql
UPDATE seats
SET status = 'held',
    hold_id = %s,
    hold_expires_at = now() + make_interval(secs => %s),
    version = version + 1
WHERE train_id = %s
  AND journey_date = %s
  AND seat_no = %s
  AND (status = 'available'
       OR (status = 'held' AND hold_expires_at < now()))
RETURNING id, seat_no;
```

3. If no row is returned, return `None`.
4. Insert a `holds` row with a Python-generated `uuid4()` id, `status='active'`, and the same expiry used by the seat.
5. Return `{"hold_id", "seat_id", "seat_no", "expires_at"}`.

`repository.expire_stale` performs the two expiry updates from the spec and commits.

`service.hold_seat` opens a pool connection, calls the repository, raises `SeatUnavailable` when it returns `None`, and returns the result.

`app/ratelimit.py` implements `allow_hold(client, user_id, limit, window_seconds=60)`: return `True` when `client is None` or `limit <= 0`; otherwise `INCR` a key containing the user id and current minute, set `EXPIRE` on the first increment, and return whether the count is within the limit. Catch Redis errors and return `True` so the limiter fails open.

`app/config.py` adds `rate_limit_per_minute` from `RATE_LIMIT_PER_MINUTE` (default 120). `app/main.py` creates a Redis client from `settings.redis_url` and calls `allow_hold` before the hold; return HTTP 429 with `{"detail": "rate_limited"}` when it returns `False`.

`app/main.py` adds the endpoint and maps `SeatUnavailable` to HTTP 409 with `{"detail": "seat_unavailable"}`. Start the sweeper in the FastAPI lifespan only when `settings.sweeper_enabled` is true; use a daemon thread that calls `service.expire_stale()` and catches/logs exceptions. The hold endpoint also calls `service.expire_stale()` before attempting the hold.

- [ ] **Step 4: Run the hold tests to verify they pass**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_hold.py tests/test_ratelimit.py -v`

Expected: PASS (4 tests).

No git commit is performed.

---

### Task 4: Idempotent payment and booking retrieval

**Files:**
- Modify: `railreserve/app/repository.py`
- Modify: `railreserve/app/service.py`
- Modify: `railreserve/app/schemas.py`
- Modify: `railreserve/app/main.py`
- Create: `railreserve/tests/test_payment.py`

**Interfaces:**
- Consumes: safe hold from Task 3.
- Produces:
  - `repository.pay_hold(conn, hold_id: UUID, idempotency_key: str, amount: Decimal) -> dict`.
  - `repository.get_booking(conn, booking_id: UUID) -> dict | None`.
  - `service.pay_hold(hold_id, idempotency_key, amount) -> dict`.
  - `schemas.PayRequest(idempotency_key: str, amount: Decimal)`.
  - `POST /api/bookings/{hold_id}/pay -> 200`, `GET /api/bookings/{booking_id} -> 200`.

- [ ] **Step 1: Write the failing payment tests**

```python
from datetime import date
from decimal import Decimal

import pytest

from app import db, repository, service
from app.errors import HoldExpired, IdempotencyKeyReused

TRAIN = "12951"
DAY = date(2026, 11, 1)


def seed_one_seat():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()


def test_payment_confirms_booking_and_payment():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    result = service.pay_hold(hold["hold_id"], "pay-1", Decimal("1500.00"))
    assert len(result["pnr"]) == 10
    with db.get_pool().connection() as conn:
        assert repository.list_seats(conn, TRAIN, DAY)[0]["status"] == "booked"
        assert conn.execute("SELECT count(*) AS n FROM payments").fetchone()["n"] == 1


def test_duplicate_payment_returns_same_booking():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    first = service.pay_hold(hold["hold_id"], "pay-1", Decimal("1500.00"))
    second = service.pay_hold(hold["hold_id"], "pay-1", Decimal("1500.00"))
    assert first["booking_id"] == second["booking_id"]
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM bookings").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM payments").fetchone()["n"] == 1


def test_expired_hold_cannot_be_paid():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s",
            (hold["hold_id"],),
        )
        conn.commit()
    with pytest.raises(HoldExpired):
        service.pay_hold(hold["hold_id"], "pay-1", Decimal("1500.00"))


def test_same_idempotency_key_on_another_hold_is_rejected():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 2)
        conn.commit()
    first = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    second = service.hold_seat(TRAIN, DAY, "S1-02", "u2")
    service.pay_hold(first["hold_id"], "pay-shared", Decimal("100.00"))
    with pytest.raises(IdempotencyKeyReused):
        service.pay_hold(second["hold_id"], "pay-shared", Decimal("100.00"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_payment.py -v`

Expected: FAIL because `service.pay_hold` and the error paths do not exist.

- [ ] **Step 3: Implement the payment flow**

`repository.pay_hold` runs one transaction:

1. `SELECT * FROM holds WHERE id = %s FOR UPDATE`.
2. Query `bookings` by `idempotency_key`. If found, return it only when its `hold_id` matches; otherwise raise `IdempotencyKeyReused`.
3. Reject missing/expired/non-active holds with `HoldExpired`.
4. Insert the booking with `pnr = str(nextval('pnr_seq'))`, the hold id, seat id, user id, and idempotency key.
5. Insert the payment with the same idempotency key and amount.
6. Update the hold to `paid` and the seat to `booked`.
7. Return `booking_id`, `pnr`, and `status`.

Catch a unique violation on the idempotency key at the service boundary, roll back, fetch the existing booking by key, and return it if the hold matches; otherwise raise `IdempotencyKeyReused`. This closes the race between two concurrent replays.

`repository.get_booking` returns the booking plus seat number, PNR, status, and timestamps.

`app/main.py` adds both endpoints and maps `HoldNotFound` to 404, `HoldExpired` and `IdempotencyKeyReused` to 409.

- [ ] **Step 4: Run the payment tests to verify they pass**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_payment.py -v`

Expected: PASS (4 tests).

No git commit is performed.

---

### Task 5: Naive booking path, reset, and stats

**Files:**
- Modify: `railreserve/app/repository.py`
- Modify: `railreserve/app/service.py`
- Modify: `railreserve/app/schemas.py`
- Modify: `railreserve/app/main.py`
- Create: `railreserve/tests/test_demo.py`

**Interfaces:**
- Consumes: reset/seed and safe hold from Tasks 2–3.
- Produces:
  - `repository.naive_read_seat(conn, train_id, journey_date, seat_no) -> dict | None`.
  - `repository.naive_confirm(conn, seat_id: int, user_id: str) -> None`.
  - `service.naive_book(train_id, journey_date, seat_no, user_id) -> dict | None`.
  - `repository.stats(conn) -> dict`.
  - `schemas.NaiveRequest` (reuse the `HoldRequest` shape).
  - `POST /api/bookings/naive`, `GET /api/demo/stats`.

- [ ] **Step 1: Write the failing demo tests**

```python
from datetime import date

from app import db, repository, service

TRAIN = "12951"
DAY = date(2026, 11, 1)


def test_naive_booking_succeeds_once_sequentially():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()
    first = service.naive_book(TRAIN, DAY, "S1-01", "u1")
    second = service.naive_book(TRAIN, DAY, "S1-01", "u2")
    assert first is not None
    assert second is None
    with db.get_pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM naive_bookings").fetchone()["n"] == 1


def test_reset_clears_naive_bookings_and_resets_stats():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()
    service.naive_book(TRAIN, DAY, "S1-01", "u1")
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 2)
        conn.commit()
        result = repository.stats(conn)
    assert result["naive_bookings"] == 0
    assert result["bookings"] == 0
    assert result["seats"]["available"] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_demo.py -v`

Expected: FAIL because the naive path and stats do not exist.

- [ ] **Step 3: Implement the naive path and stats**

`service.naive_book`:

1. Read the seat with `naive_read_seat`.
2. Return `None` if the seat is missing or not `available`.
3. Sleep `settings.naive_delay_ms / 1000`.
4. Call `naive_confirm`, which updates the seat to `booked` and inserts a `naive_bookings` row without a status guard or uniqueness constraint.
5. Return `{"naive_booking_id": ..., "seat_no": ...}`.

`repository.stats` returns:

```json
{
  "seats": {"available": 0, "held": 0, "booked": 0},
  "bookings": 0,
  "payments": 0,
  "naive_bookings": 0
}
```

`app/main.py` adds `POST /api/bookings/naive` and `GET /api/demo/stats`.

- [ ] **Step 4: Run the demo tests to verify they pass**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_demo.py -v`

Expected: PASS (2 tests).

No git commit is performed.

---

### Task 6: Concurrency proof tests

**Files:**
- Create: `railreserve/tests/test_concurrency.py`
- Modify: `railreserve/tests/conftest.py` (pool size, if needed)

**Interfaces:**
- Consumes: `service.hold_seat`, `repository.reset_demo`.
- Produces: invariant tests for exactly-one-winner and all-seats-once.

- [ ] **Step 1: Write the concurrency tests**

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from app import db, repository, service
from app.errors import SeatUnavailable

TRAIN = "12951"
DAY = date(2026, 11, 1)


def test_exactly_one_hold_wins_for_one_seat():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()

    barrier = Barrier(20)

    def attempt(i):
        barrier.wait()
        try:
            service.hold_seat(TRAIN, DAY, "S1-01", f"u{i}")
            return "ok"
        except SeatUnavailable:
            return "conflict"

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))
    assert results.count("ok") == 1
    assert results.count("conflict") == 19


def test_each_of_50_seats_is_held_once_under_200_attempts():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 50)
        conn.commit()

    barrier = Barrier(50)

    def attempt(i):
        seat_no = f"S1-{i % 50 + 1:02d}"
        barrier.wait()
        try:
            return service.hold_seat(TRAIN, DAY, seat_no, f"u{i}")["seat_id"]
        except SeatUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(attempt, range(200)))
    winners = [seat_id for seat_id in results if seat_id is not None]
    assert len(winners) == 50
    assert len(set(winners)) == 50
```

- [ ] **Step 2: Run the tests to verify they fail or expose a race**

Run: `cd railreserve && docker compose run --rm api1 pytest tests/test_concurrency.py -v`

Expected: PASS if the Task 3 hold logic is correct. If it fails with duplicate winners or deadlocks, fix the conditional update and the transaction scope before continuing.

- [ ] **Step 3: Verify the pool can serve concurrent connections**

Set `max_size=30` in the test pool initialization. Confirm the tests pass with 50 workers; if they time out, raise `max_size` to 60 rather than serializing the test.

- [ ] **Step 4: Run the full test suite**

Run: `cd railreserve && docker compose run --rm api1 pytest -v`

Expected: all tests pass.

No git commit is performed.

---

### Task 7: Nginx, dashboard, and failover verification

**Files:**
- Create: `railreserve/nginx.conf`
- Create: `railreserve/app/static/index.html`
- Modify: `railreserve/docker-compose.yml`
- Modify: `railreserve/README.md`

**Interfaces:**
- Consumes: API endpoints from Tasks 2–5.
- Produces: `http://localhost:8080` serving the dashboard and proxying `/api/` and `/health`.

- [ ] **Step 1: Write the Nginx configuration**

Use an `upstream rail_api` with `api1:8000` and `api2:8000`, `max_fails=1`, and `fail_timeout=5s`. Serve `app/static` as the root. Proxy `/api/` and `/health` to the upstream with `proxy_next_upstream error timeout http_502` and `proxy_next_upstream_tries 2`.

- [ ] **Step 2: Write the dashboard**

`app/static/index.html` displays:

- A seat grid fetched from `/api/seats?train_id=12951&journey_date=2026-11-01`.
- Counts fetched from `/api/demo/stats`.
- A Reset button that posts to `/api/demo/reset` with 50 seats.
- A Refresh button.

Use plain HTML, CSS, and `fetch`; no build step and no external CDN.

- [ ] **Step 3: Wire Compose**

Add an `nginx` service using `nginx:1.27-alpine`, publishing `8080:80`, mounting `./nginx.conf` read-only and `./app/static` read-only, depending on `api1` and `api2`. Add API healthchecks using Python's `urllib.request` against `http://localhost:8000/health`.

- [ ] **Step 4: Verify the stack and failover manually**

Run:

```bash
cd railreserve
docker compose up --build -d
curl -s http://localhost:8080/health
curl -s -X POST http://localhost:8080/api/demo/reset \
  -H 'content-type: application/json' \
  -d '{"train_id":"12951","journey_date":"2026-11-01","seat_count":2}'
curl -s -X POST http://localhost:8080/api/bookings/hold \
  -H 'content-type: application/json' \
  -d '{"train_id":"12951","journey_date":"2026-11-01","seat_no":"S1-01","user_id":"u1"}'
docker compose stop api1
curl -s -X POST http://localhost:8080/api/bookings/hold \
  -H 'content-type: application/json' \
  -d '{"train_id":"12951","journey_date":"2026-11-01","seat_no":"S1-02","user_id":"u2"}'
docker compose start api1
```

Expected: health returns `{"status":"ok"}`; both hold requests return 201; the second succeeds with `api1` stopped.

No git commit is performed.

---

### Task 8: Demo script, README, and presentation outline

**Files:**
- Create: `railreserve/scripts/demo.py`
- Modify: `railreserve/README.md`
- Create: `railreserve/docs/presentation-outline.md`

**Interfaces:**
- Consumes: the running stack at `BASE_URL` (default `http://localhost:8080`).
- Produces: a script with six scenarios and a non-zero exit on safe-mode invariant failure.

- [ ] **Step 1: Write the demo script**

Use `httpx.Client(timeout=10)` and `ThreadPoolExecutor`. Implement:

1. `naive_race`: reset 1 seat; fire 20 concurrent naive bookings; print success count and `naive_bookings` count; expect more than one success.
2. `safe_race`: reset 1 seat; fire 20 concurrent holds; expect exactly 1 HTTP 201 and 19 HTTP 409.
3. `inventory_sweep`: reset 50 seats; fire 200 concurrent holds across the 50 seats; expect exactly 50 successes and 50 distinct seat numbers.
4. `idempotent_payment`: reset 1 seat; hold; fire 10 concurrent payments with the same key; expect one distinct booking id and `payments == 1`.
5. `expiry`: reset 1 seat; hold; sleep `HOLD_TTL_SECONDS + 2`; hold again; expect success.
6. `failover`: print the shell commands to stop `api1` and retry a hold; do not attempt to control Docker from the script.

Read `BASE_URL` and `HOLD_TTL_SECONDS` from the environment. Print a PASS/FAIL line per scenario and exit 1 if any safe invariant fails.

- [ ] **Step 2: Run the script against the running stack**

Run: `cd railreserve && docker compose up -d && docker compose exec -e BASE_URL=http://nginx api1 python scripts/demo.py`

Expected: naive race reports more than one winner; safe race, inventory sweep, idempotent payment, and expiry all PASS.

- [ ] **Step 3: Write the README**

Include:

- Architecture diagram and component list.
- `docker compose up --build -d` quick start.
- Dashboard URL and reset instructions.
- Test command: `docker compose run --rm api1 pytest -v`.
- Demo command and expected output.
- Failover commands.
- Scope and non-goals.
- A note that IRCTC facts are public reporting and the architecture is the team's proposal.

- [ ] **Step 4: Write the presentation outline**

Create 12 slides with speaker notes:

1. Title and problem.
2. IRCTC scale and Tatkal (with citations).
3. Naive race timeline.
4. Requirements.
5. Proposed architecture.
6. Safe hold flow.
7. Payment idempotency and expiry.
8. Strong vs eventual consistency.
9. Live demo results.
10. Node failure and recovery.
11. Trade-offs and alternatives.
12. Lessons learned and Q&A backup.

No git commit is performed.

---

### Task 9: End-to-end verification and demo backup

**Files:**
- Modify: `railreserve/README.md` only if verification exposes a gap.
- Create: `railreserve/demo-output.txt` (captured script output; optional but recommended).

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified commands and a fallback recording/output for the presentation.

- [ ] **Step 1: Run the full automated suite**

Run: `cd railreserve && docker compose run --rm api1 pytest -v`

Expected: all tests pass, including the two concurrency tests.

- [ ] **Step 2: Run the live demo and capture output**

Run:

```bash
cd railreserve
docker compose up --build -d
docker compose exec -e BASE_URL=http://nginx api1 python scripts/demo.py | tee demo-output.txt
```

Expected: all safe scenarios PASS; naive race shows multiple winners.

- [ ] **Step 3: Verify failover from a clean state**

Run the Task 7 failover commands again after a reset. Expected: the second hold succeeds while `api1` is stopped.

- [ ] **Step 4: Verify the stack restarts cleanly**

Run:

```bash
cd railreserve
docker compose down -v
docker compose up --build -d
curl -s http://localhost:8080/health
```

Expected: health returns `{"status":"ok"}` and the dashboard loads at `http://localhost:8080/`.

- [ ] **Step 5: Final content check**

Confirm the README and slides:

- Separate public IRCTC facts from the proposed design.
- State the exact demo invariants.
- Include the fallback `demo-output.txt` or a screen recording reference.
- Do not include secrets or real payment credentials.

No git commit is performed.
