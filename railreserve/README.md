# RailReserve

RailReserve is a small distributed-systems demo for the DCS FA2 case-study
presentation. It models the part of IRCTC that matters for the assignment:
two API replicas race for one seat, and only one of them may win.

The demo proves four things:

1. A conditional `UPDATE` in Postgres plus a partial unique index allows exactly
   one winner when 20 concurrent requests target the same seat.
2. A deliberately naive read-delay-write path lets all 20 requests win, which
   shows why the guard matters.
3. Payment is idempotent: replaying the same idempotency key returns the original
   booking and PNR instead of charging twice.
4. Nginx keeps serving traffic when one API replica is stopped.

## Architecture

```mermaid
flowchart LR
  B[Browser dashboard] --> N[Nginx :8080]
  N --> A1[api1 FastAPI]
  N --> A2[api2 FastAPI]
  A1 --> P[(Postgres 16)]
  A2 --> P
  A1 -. fail-open .-> R[(Redis 7)]
  A2 -. fail-open .-> R
```

- Postgres is the authoritative inventory store.
- Redis is used only for per-user rate limiting and is not on the booking
  critical path. If Redis is down, holds still work.
- The API is stateless; any replica can handle any request.
- A background sweeper releases seats whose hold TTL has expired.

## Quick start

```bash
docker compose up --build -d
```

Open <http://localhost:8080>. The dashboard resets the demo on load. If the
Postgres container was created before the schema was added, run
`docker compose down` first so `db/init.sql` runs again.

The API is also reachable directly through Nginx:

```bash
curl http://localhost:8080/health
```

## Demo flow

### 1. Safe race

Reset the demo, then run 20 concurrent holds for `S1-01`:

```bash
seq 1 20 | xargs -P20 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8080/api/bookings/hold \
  -H 'Content-Type: application/json' \
  -d '{"train_id":"12951","journey_date":"2026-11-01","seat_no":"S1-01","user_id":"safe-{}"}'
```

Expected result: one `201` and nineteen `409` responses. The seat is `held`
once, and the stats endpoint reports `held: 1`.

The critical SQL is a single statement:

```sql
UPDATE seats
SET status = 'held', hold_id = %s, hold_expires_at = now() + ...
WHERE train_id = %s AND journey_date = %s AND seat_no = %s
  AND (status = 'available' OR (status = 'held' AND hold_expires_at < now()))
RETURNING id, seat_no, hold_expires_at;
```

A second partial unique index enforces the invariant at the schema level:

```sql
CREATE UNIQUE INDEX one_active_hold_per_seat
  ON holds (seat_id) WHERE status = 'active';
```

### 2. Naive race

Reset, then send the same 20 requests to `/api/naive/hold`. The naive path
reads availability, sleeps for `NAIVE_DELAY_MS`, and writes without a guard.
Expected result in the CLI demo: 20 winners for one seat. The stats endpoint
reports `naive_winners: 20`. The browser dashboard may show fewer winners
because browsers cap concurrent connections per host; the CLI script sends all
20 requests at once.

### 3. Idempotent payment

Hold a seat, then pay twice with the same key:

```bash
curl -X POST http://localhost:8080/api/bookings/<hold_id>/pay \
  -H 'Content-Type: application/json' \
  -d '{"idempotency_key":"demo-key-1","amount":"1200.00"}'
```

Both calls return the same `booking_id` and `pnr`. The second response has
`"replayed": true`.

### 4. Failover

```bash
docker compose stop api1
curl http://localhost:8080/health
docker compose start api1
```

Nginx routes around the stopped replica. The `X-Upstream` response header shows
which replica handled the request.

## Screenshots

- `docs/dashboard-safe-race.png` — one winner and nineteen rejected holds.
- `docs/dashboard-payment.png` — the second payment replays the same booking.
- `docs/dashboard-naive-race.png` — multiple winners for one seat.

## One-command demo

```bash
./scripts/demo.sh
```

The wrapper runs the Python driver inside the API container:

```bash
docker compose exec -e BASE_URL=http://nginx api1 python scripts/demo.py
```

The driver runs six scenarios and prints `PASS`/`FAIL` for each:

| Scenario | Invariant |
| --- | --- |
| `naive_race` | More than one winner for one seat |
| `safe_race` | Exactly one `201`, nineteen `409` |
| `inventory_sweep` | 200 holds across 50 seats → 50 winners, 50 distinct seats |
| `idempotent_payment` | 10 concurrent payments with one key → one booking, one payment |
| `expiry` | A forced-expired hold can be reclaimed |
| `failover` | Health is live and the stop/start commands are printed |

The script exits non-zero if any scenario fails. Capture output with:

```bash
./scripts/demo.sh | tee demo-output.txt
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/demo/reset` | Truncate and seed the demo seats |
| `GET` | `/api/seats` | List seats for a train and date |
| `POST` | `/api/bookings/hold` | Safe hold with conditional update |
| `POST` | `/api/bookings/{hold_id}/pay` | Idempotent payment and booking |
| `GET` | `/api/bookings/{booking_id}` | Fetch a booking and PNR |
| `POST` | `/api/naive/hold` | Unsafe read-delay-write hold |
| `GET` | `/api/stats` | Seat counts plus winner counts |

## Tests

```bash
docker compose run --rm api1 pytest -v
```

Expected: `15 passed`. The suite includes a 20-thread safe race, a 20-thread
naive race with a barrier that guarantees the read-before-write interleaving,
and 10 concurrent payments with the same idempotency key.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://rail:rail@postgres:5432/railreserve` | Postgres connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `HOLD_TTL_SECONDS` | `300` (`120` in Compose) | Hold lifetime |
| `NAIVE_DELAY_MS` | `150` (`300` in Compose) | Race window for the naive path |
| `SWEEPER_ENABLED` | `true` | Run the expiry sweeper |
| `SWEEPER_INTERVAL_SECONDS` | `2` | Sweeper period |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per-user hold limit, `0` disables |

## Public IRCTC facts used in the presentation

These are public figures, not properties of this demo:

- IRCTC's record is 30,155 tickets booked in one minute.
- IRCTC books roughly 13.88 lakh tickets per day (FY 2024-25); about 86.38% of
  bookings are digital.
- The next-generation PRS targets 1.5 lakh bookings per minute and 40 lakh
  enquiries per minute.
- Tatkal opens at 10:00 for AC classes and 11:00 for non-AC classes.

The demo is intentionally smaller: it isolates the double-booking problem and
the coordination primitives a real system needs at that scale.

## Scope and non-goals

In scope: the seat-hold invariant, idempotent payment, hold expiry, two API
replicas behind Nginx, a naive comparison path, and a reproducible demo.

Out of scope: a real IRCTC integration, a payment gateway, authentication,
waitlists, quotas, Tatkal rules, notifications, and multi-region deployment.
The naive path is a teaching control, not a product feature.

## Limitations

- Single Postgres primary. A production system would add replication, failover,
  and sharding or seat-range partitioning.
- The seat map is seeded per demo run; there is no waitlist, quota, or Tatkal
  rules engine.
- Rate limiting is a fixed-window counter, adequate for the demo but not a
  production-grade limiter.
- The naive path exists only to make the race visible; it is never used by the
  booking flow.

## Layout

```
app/            FastAPI application, repository, service, rate limiting
dashboard/      Static demo dashboard served by Nginx
db/init.sql     Schema and indexes
nginx/          Nginx upstream and proxy configuration
scripts/        Demo driver
tests/          Pytest suite, including concurrency proofs
docs/           Presentation outline
```
