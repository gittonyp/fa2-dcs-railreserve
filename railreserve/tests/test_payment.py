from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest

from app import db, repository, service
from app.errors import HoldExpired

TRAIN = "12951"
DAY = date(2026, 11, 1)


def seed_one_seat():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()


def test_payment_is_idempotent_and_marks_seat_booked():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    first = service.pay_hold(hold["hold_id"], "pay-1", Decimal("1200.00"))
    second = service.pay_hold(hold["hold_id"], "pay-1", Decimal("1200.00"))
    assert first["booking_id"] == second["booking_id"]
    assert second["replayed"] is True
    assert first["seat_no"] == "S1-01"
    with db.get_pool().connection() as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM bookings WHERE idempotency_key = 'pay-1'"
        ).fetchone()["n"]
    assert count == 1


def test_concurrent_payment_with_same_key_creates_one_payment():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    barrier = Barrier(10)

    def pay(_: int) -> dict:
        barrier.wait(timeout=5)
        return service.pay_hold(hold["hold_id"], "pay-concurrent", Decimal("1200.00"))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(pay, range(10)))

    assert len({result["booking_id"] for result in results}) == 1
    with db.get_pool().connection() as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM payments WHERE idempotency_key = 'pay-concurrent'"
        ).fetchone()["n"]
    assert count == 1


def test_payment_after_expiry_is_rejected():
    seed_one_seat()
    hold = service.hold_seat(TRAIN, DAY, "S1-01", "u1")
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE holds SET expires_at = now() - interval '1 second' WHERE id = %s",
            (hold["hold_id"],),
        )
        conn.commit()
    with pytest.raises(HoldExpired):
        service.pay_hold(hold["hold_id"], "pay-expired", Decimal("1200.00"))
