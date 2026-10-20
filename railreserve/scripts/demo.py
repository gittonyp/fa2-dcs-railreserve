#!/usr/bin/env python3
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import psycopg

BASE_URL = os.getenv("BASE_URL", "http://localhost:8080").rstrip("/")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://rail:rail@localhost:55432/railreserve"
)
HOLD_TTL_SECONDS = int(os.getenv("HOLD_TTL_SECONDS", "120"))
TRAIN = os.getenv("TRAIN_ID", "12951")
DAY = os.getenv("JOURNEY_DATE", "2026-11-01")
TARGET = os.getenv("TARGET_SEAT", "S1-01")

client = httpx.Client(
    timeout=10.0,
    limits=httpx.Limits(max_connections=256, max_keepalive_connections=64),
)


def url(path: str) -> str:
    return f"{BASE_URL}{path}"


def wait_for_health(timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get(url("/health")).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{BASE_URL}/health did not become ready")


def payload(seat_no: str, user_id: str) -> dict:
    return {
        "train_id": TRAIN,
        "journey_date": DAY,
        "seat_no": seat_no,
        "user_id": user_id,
    }


def reset(seat_count: int) -> None:
    response = client.post(
        url("/api/demo/reset"),
        json={"train_id": TRAIN, "journey_date": DAY, "seat_count": seat_count},
    )
    response.raise_for_status()


def stats() -> dict:
    response = client.get(
        url("/api/stats"), params={"train_id": TRAIN, "journey_date": DAY}
    )
    response.raise_for_status()
    return response.json()


def hold(seat_no: str, user_id: str) -> httpx.Response:
    return client.post(url("/api/bookings/hold"), json=payload(seat_no, user_id))


def naive_hold(seat_no: str, user_id: str) -> httpx.Response:
    return client.post(url("/api/naive/hold"), json=payload(seat_no, user_id))


def db_count(query: str, params: tuple) -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(query, params).fetchone()[0]


def run_concurrently(count: int, worker) -> list:
    barrier = Barrier(count)

    def run(index: int):
        barrier.wait(timeout=10)
        return worker(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def naive_race() -> tuple[bool, str]:
    reset(1)
    codes = run_concurrently(
        20, lambda i: naive_hold(TARGET, f"naive-{i}").status_code
    )
    winners = codes.count(201)
    current = stats()
    passed = winners > 1 and current["naive_winners"] > 1
    return (
        passed,
        f"{winners}/20 requests won; stats.naive_winners={current['naive_winners']}",
    )


def safe_race() -> tuple[bool, str]:
    reset(1)
    codes = run_concurrently(20, lambda i: hold(TARGET, f"safe-{i}").status_code)
    current = stats()
    passed = (
        codes.count(201) == 1
        and codes.count(409) == 19
        and current["held"] == 1
    )
    return (
        passed,
        f"201={codes.count(201)}, 409={codes.count(409)}, stats.held={current['held']}",
    )


def inventory_sweep() -> tuple[bool, str]:
    reset(50)
    total = 200

    def attempt(index: int):
        seat_no = f"S1-{(index % 50) + 1:02d}"
        response = hold(seat_no, f"sweep-{index}")
        return response.status_code, seat_no

    results = run_concurrently(total, attempt)
    winners = [seat for code, seat in results if code == 201]
    counts = {}
    for code, _ in results:
        counts[code] = counts.get(code, 0) + 1
    passed = (
        len(winners) == 50
        and len(set(winners)) == 50
        and counts.get(409, 0) == 150
    )
    return (
        passed,
        f"201={len(winners)}, distinct seats={len(set(winners))}, "
        f"409={counts.get(409, 0)}, statuses={counts}",
    )


def idempotent_payment() -> tuple[bool, str]:
    reset(1)
    response = hold(TARGET, "payer")
    if response.status_code != 201:
        return False, f"hold failed with {response.status_code}"
    hold_id = response.json()["hold_id"]
    key = f"demo-pay-{time.time_ns()}"

    def pay(_: int):
        response = client.post(
            url(f"/api/bookings/{hold_id}/pay"),
            json={"idempotency_key": key, "amount": "1200.00"},
        )
        body = response.json()
        return response.status_code, body

    results = run_concurrently(10, pay)
    statuses = [code for code, _ in results]
    booking_ids = {
        body["booking_id"] for code, body in results if code == 200
    }
    payments = db_count(
        "SELECT count(*) FROM payments WHERE idempotency_key = %s", (key,)
    )
    passed = (
        statuses.count(200) == 10
        and len(booking_ids) == 1
        and payments == 1
    )
    pnr = next(
        (body["pnr"] for code, body in results if code == 200), "none"
    )
    return (
        passed,
        f"200={statuses.count(200)}, booking_ids={len(booking_ids)}, "
        f"payments={payments}, pnr={pnr}",
    )


def expiry() -> tuple[bool, str]:
    reset(1)
    response = hold(TARGET, "expiry-first")
    if response.status_code != 201:
        return False, f"first hold failed with {response.status_code}"
    first = response.json()
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s",
            (first["hold_id"],),
        )
        conn.execute(
            "UPDATE seats SET hold_expires_at = now() - interval '1 second' "
            "WHERE id = %s",
            (first["seat_id"],),
        )
        conn.commit()
    second = hold(TARGET, "expiry-second")
    passed = second.status_code == 201
    return (
        passed,
        f"forced expiry into the past; second hold={second.status_code}; "
        f"configured ttl={HOLD_TTL_SECONDS}s",
    )


def failover() -> tuple[bool, str]:
    response = client.get(url("/health"))
    print("  docker compose stop api1")
    print("  curl -i http://localhost:8080/health")
    print("  curl -i http://localhost:8080/api/seats?train_id=12951&journey_date=2026-11-01")
    print("  docker compose start api1")
    return response.status_code == 200, f"health={response.status_code}; commands printed above"


def main() -> int:
    print(f"BASE_URL={BASE_URL}")
    print(f"DATABASE_URL={DATABASE_URL}")
    print(f"HOLD_TTL_SECONDS={HOLD_TTL_SECONDS}")
    scenarios = [
        ("naive_race", naive_race),
        ("safe_race", safe_race),
        ("inventory_sweep", inventory_sweep),
        ("idempotent_payment", idempotent_payment),
        ("expiry", expiry),
        ("failover", failover),
    ]
    failures = 0
    try:
        try:
            wait_for_health()
            print(f"health: ready at {BASE_URL}")
        except Exception as exc:
            print(f"FAIL health: {exc}")
            return 1
        for name, scenario in scenarios:
            try:
                passed, detail = scenario()
            except Exception as exc:
                passed, detail = False, f"{type(exc).__name__}: {exc}"
            label = "PASS" if passed else "FAIL"
            print(f"{label} {name}: {detail}")
            if not passed:
                failures += 1
    finally:
        client.close()
    print(f"{len(scenarios) - failures}/{len(scenarios)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
