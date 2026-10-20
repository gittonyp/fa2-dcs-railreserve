# RailReserve: IRCTC-Inspired Double-Booking Demo — Design

## Context

This project supports the DCS FA2 case-study presentation (10 marks, group of 4). The chosen topic is **Preventing Double Booking in a Railway Reservation System** (topic 6). The FA2 rubric weights presentation (5 marks), conceptual knowledge (3), and Q&A (2).

IRCTC is the case study, not the thing being cloned. Publicly reported facts used in the presentation:

- Record of 30,155 ticket bookings in one minute on 12 March 2025.
- About 13.88 lakh tickets booked online per day in FY 2024–25; 86.38% of reserved tickets booked digitally.
- A new cloud-enabled Passenger Reservation System is being phased in from August 2026, targeting more than 1.5 lakh bookings per minute and 40 lakh enquiries per minute, up from roughly 32,000 bookings and 4 lakh enquiries.
- Tatkal booking opens at 10:00 for AC classes and 11:00 for non-AC classes, producing an extreme thundering-herd workload.

Claims about IRCTC's internal use of Redis, Kafka, or a virtual queue are not publicly confirmed and must be presented as **our proposed design**, not as IRCTC's actual implementation.

## Goal

Build a small, reproducible demo that shows:

1. Why naive read-then-write booking causes double booking under concurrency.
2. How an authoritative database constraint and atomic seat hold prevent it.
3. How a payment callback is made idempotent.
4. How the system survives one API node failing.

The demo is the visual aid for the case study; it is not a production booking product.

## Success Criteria

- `docker compose up --build` starts the complete stack on a laptop.
- Naive mode with 1 seat and 20 concurrent requests produces more than one successful booking.
- Safe mode with 1 seat and 20 concurrent requests produces exactly 1 success and 19 conflicts.
- Safe mode with 50 seats and 200 concurrent requests produces exactly 50 bookings and no duplicate seat allocations.
- Sending the same payment callback 10 times creates exactly 1 booking and 1 payment.
- An unpaid hold expires and the seat becomes bookable again.
- Stopping one API container does not stop bookings through Nginx.
- The demo script prints machine-checkable counts for each scenario.
- The presentation clearly separates public IRCTC facts from the proposed architecture.

## Non-Goals

- Real authentication, authorization, or user management.
- A real payment gateway; payments are simulated.
- PNR cancellation, refunds, waiting lists, RAC, quota management, or multi-leg journeys.
- Train search, fares, admin workflows, or a mobile app.
- Kubernetes, cloud deployment, or production hardening.
- Multi-region replication or consensus; the demo uses one Postgres primary.
- Copying IRCTC branding, data, or proprietary internals.

## Architecture

```
Browser dashboard (static HTML/JS)
              |
            Nginx
        load balance + static
          /            \
     api-1            api-2          FastAPI, 2 replicas
          \            /
             Postgres               authoritative inventory
                 |
              Redis                 rate limiting + demo cache (not correctness)
```

**Key decision:** correctness lives in Postgres, not in a Redis lock. Redis is used only for non-authoritative concerns such as rate limiting and an optional availability cache. This avoids the Redlock safety debate and gives a clear teaching point for Q&A.

**Deployment:** Docker Compose with services `nginx`, `api1`, `api2`, `postgres`, `redis`. The API image is shared; replicas differ only by container name and port mapping.

## Components

### Nginx

- Serves `app/static/index.html` at `/`.
- Proxies `/api/` to `api1:8000` and `api2:8000` with round-robin.
- Uses `max_fails=1 fail_timeout=5s` and `proxy_next_upstream error timeout http_502` so a stopped API container is bypassed quickly during the failover demo.
- Adds no caching in the MVP.

### API (FastAPI, Python 3.12)

Synchronous endpoints using `psycopg` with a connection pool. FastAPI runs sync endpoints in a thread pool, so concurrent requests reach Postgres concurrently.

Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness; returns `{"status":"ok"}` |
| GET | `/api/seats?train_id=...&journey_date=...` | Seat list with status and hold expiry |
| POST | `/api/bookings/hold` | Atomically hold one seat |
| POST | `/api/bookings/{hold_id}/pay` | Idempotent simulated payment and confirmation |
| GET | `/api/bookings/{booking_id}` | Booking details |
| POST | `/api/bookings/naive` | Deliberately racy booking path for the demo; writes to `naive_bookings` |
| POST | `/api/demo/reset` | Reset seats and truncate bookings/payments/holds/naive_bookings |
| GET | `/api/demo/stats` | Seat, booking, payment, and naive-booking counts for the dashboard/script |

Hold request:

```json
{"train_id":"12951","journey_date":"2026-11-01","seat_no":"S1-01","user_id":"u1"}
```

Hold response `201`:

```json
{"hold_id":"...","seat_id":1,"seat_no":"S1-01","expires_at":"2026-10-20T12:05:00Z"}
```

Conflict response `409`:

```json
{"detail":"seat_unavailable"}
```

Payment request:

```json
{"idempotency_key":"pay-u1-001","amount":1500.00}
```

Payment response `200`:

```json
{"booking_id":"...","pnr":"4821937461","status":"confirmed"}
```

`POST /api/bookings/naive` accepts the same body shape as hold, sleeps `NAIVE_DELAY_MS` (default 150 ms; the demo stack uses 300 ms) between read and write, and books without a hold. It exists only to demonstrate the bug.

### Postgres

Schema in `db/init.sql`:

```sql
CREATE TABLE seats (
    id SERIAL PRIMARY KEY,
    train_id TEXT NOT NULL,
    journey_date DATE NOT NULL,
    seat_no TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'held', 'booked')),
    hold_id UUID,
    hold_expires_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 0,
    UNIQUE (train_id, journey_date, seat_no)
);

CREATE TABLE holds (
    id UUID PRIMARY KEY,
    seat_id INTEGER NOT NULL REFERENCES seats(id),
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paid', 'expired', 'cancelled')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_active_hold_per_seat
    ON holds (seat_id) WHERE status = 'active';

CREATE TABLE bookings (
    id UUID PRIMARY KEY,
    hold_id UUID NOT NULL UNIQUE REFERENCES holds(id),
    seat_id INTEGER NOT NULL UNIQUE REFERENCES seats(id),
    user_id TEXT NOT NULL,
    pnr TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'confirmed',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE payments (
    id UUID PRIMARY KEY,
    booking_id UUID NOT NULL REFERENCES bookings(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'captured',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE naive_bookings (
    id UUID PRIMARY KEY,
    seat_id INTEGER NOT NULL REFERENCES seats(id),
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE pnr_seq START WITH 1000000000;
```

The `bookings.seat_id` unique constraint is the final guard against double allocation. The seat row is also updated atomically, so both layers agree. `naive_bookings` deliberately has no uniqueness constraint; it exists only to make the race observable and is cleared on reset.

### Redis

Used for a simple rate limit on hold requests (`INCR` + `EXPIRE`) and an optional 2-second availability cache. Neither is required for correctness. If Redis is unavailable, booking correctness must still hold; the MVP may fail open on rate limiting.

## Booking Flow

### Safe hold

1. Read configuration from environment (`DATABASE_URL`, `REDIS_URL`, `HOLD_TTL_SECONDS`, `NAIVE_DELAY_MS`, `SWEEPER_ENABLED`). The default hold TTL is 300 seconds; the demo compose stack uses 10 seconds so the expiry scenario is quick.
2. Expire stale holds older than `now()` before serving (also done by a background sweeper).
3. In one transaction, execute:

```sql
UPDATE seats
SET status = 'held',
    hold_id = %s,
    hold_expires_at = now() + (%s || ' seconds')::interval,
    version = version + 1
WHERE train_id = %s
  AND journey_date = %s
  AND seat_no = %s
  AND (status = 'available'
       OR (status = 'held' AND hold_expires_at < now()))
RETURNING id;
```

4. If no row is returned, return `409 seat_unavailable`.
5. Insert the hold row and commit.
6. Return the hold id and expiry.

The conditional `UPDATE` takes a row lock. Concurrent requests serialize on the same seat row; exactly one sees `status = 'available'`.

### Payment

1. Begin transaction.
2. Select the hold `FOR UPDATE`.
3. If a booking already exists for this `idempotency_key`, return that booking (idempotent replay). If the existing booking's `hold_id` differs from the requested hold, return `409 idempotency_key_reused`.
4. If the hold is missing, expired, or not active, return `409`.
5. Insert `bookings` and `payments` with the same idempotency key; update the hold to `paid` and the seat to `booked`.
6. Commit and return the PNR.

A duplicate callback with the same key returns the original booking. A different key for the same hold returns `409` because `bookings.hold_id` is unique.

### Expiry

A background sweeper runs every 2 seconds:

```sql
UPDATE holds SET status = 'expired'
WHERE status = 'active' AND expires_at < now();

UPDATE seats SET status = 'available', hold_id = NULL, hold_expires_at = NULL
WHERE status = 'held' AND hold_expires_at < now();
```

The hold endpoint also performs the seat-expiry update before attempting a new hold, so expiry works even if the sweeper is delayed.

### Naive path

`POST /api/bookings/naive`:

1. `SELECT status FROM seats WHERE ...`.
2. Sleep `NAIVE_DELAY_MS` (default 150 ms).
3. If status is `available`, `UPDATE seats SET status = 'booked'` and insert a row into `naive_bookings`.
4. No row-level guard on the update and no uniqueness constraint on `naive_bookings`.

Under concurrency, several requests read `available` and all write, producing multiple successful bookings for one seat. The demo script counts rows in `naive_bookings` and resets the data before and after this scenario.

## Demo Script

`scripts/demo.py` runs against Nginx (`BASE_URL`, default `http://localhost:8080`). It uses `httpx` and `concurrent.futures.ThreadPoolExecutor`. Scenarios:

1. **Naive race:** reset 1 seat; 20 concurrent naive bookings; print successes and duplicate bookings. Expect more than one success.
2. **Safe race:** reset 1 seat; 20 concurrent holds; print `201`, `409`, and distinct seat allocations. Expect 1 success.
3. **Inventory sweep:** reset 50 seats; 200 concurrent holds; print distinct seats held. Expect 50.
4. **Idempotent payment:** reset 1 seat; hold; send the same payment 10 times; print booking count and payment count. Expect 1 each.
5. **Expiry:** reset 1 seat; hold; wait `HOLD_TTL_SECONDS + 2`; try a new hold. Expect success.
6. **Node failure:** documented as a shell step (`docker compose stop api1`), not automated inside the script; verify a new hold still succeeds.

Each scenario returns a pass/fail boolean. The script exits non-zero if a safe-mode invariant fails.

## Dashboard

`app/static/index.html` is a dependency-free page:

- Seat grid fetched from `/api/seats`.
- Status colors: available, held, booked.
- Buttons: Reset, Refresh.
- Stats from `/api/demo/stats`: seats available/held/booked, bookings, payments.
- A results panel that can display the last demo scenario output pasted in, or simply the live counts.

The terminal demo script is the primary evidence; the dashboard is the visual aid.

## Testing

- `pytest` tests run against a real Postgres database (`TEST_DATABASE_URL`), using a dedicated test schema/database created by the test fixture. Docker Compose provides the database.
- Unit tests cover: hold success, hold conflict, expired hold reclaim, payment success, duplicate payment idempotency, expired hold payment rejection, naive endpoint basic behavior.
- Concurrency test: use `ThreadPoolExecutor` with 20 workers calling the service's hold function against the test DB; assert exactly 1 success and 19 conflicts. This test does not depend on HTTP.
- Integration test: start the API with `uvicorn` or use FastAPI `TestClient` for endpoint contracts; for real concurrency, the demo script is the end-to-end check.
- Manual verification: `docker compose up --build`, run `python scripts/demo.py`, stop one API container, rerun a hold.

## Presentation Outline

1. Title and the double-booking problem.
2. IRCTC scale and Tatkal thundering herd (public facts with sources).
3. Why naive booking fails (race timeline).
4. Requirements: correctness, availability, latency.
5. Proposed architecture and booking flow.
6. Strong consistency for allocation vs eventual consistency for display.
7. Payment idempotency and hold expiry.
8. Live demo results.
9. Node failure and recovery.
10. Trade-offs: DB constraint vs Redis lock; queue vs reject; 2PC vs saga.
11. Lessons learned and Q&A backup.

## Team Split

| Member | Primary responsibility |
|---|---|
| A | IRCTC case study, slides, citations, Q&A backup |
| B | Booking and payment correctness, SQL, tests |
| C | Docker, Nginx, load script, failure injection |
| D | Dashboard, demo narration, screenshot/backup recording |

Every member should be able to explain the safe hold and idempotency flows.

## Risks and Mitigations

- **Docker resource limits:** use small images; Postgres is the only heavy service.
- **Browser connection limits:** run the concurrency demo from the Python script, not the browser.
- **Demo failure on stage:** record a backup video and include expected output in the slides.
- **Scope creep:** auth, real payments, cancellation, and UI polish are explicitly out of scope.
- **Misrepresenting IRCTC:** label public facts and proposed design separately.
- **Flaky concurrency test:** assert only invariants (one winner, no duplicate seats), never timing.

## Decisions

- Python 3.12 + FastAPI + psycopg 3, not Node. The SQL is the teaching artifact.
- Postgres is authoritative; Redis is optional and non-authoritative.
- Two API replicas behind Nginx to make the multi-instance story visible.
- Payments are simulated; idempotency is still exercised through the same key.
- No git commits are performed unless the user explicitly requests them.
