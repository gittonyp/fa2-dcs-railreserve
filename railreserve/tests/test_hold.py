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
