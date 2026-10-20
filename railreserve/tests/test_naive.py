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


def test_naive_hold_creates_booking(monkeypatch):
    seed_one_seat()
    monkeypatch.setattr(service, "sleep", lambda _: None)
    result = service.naive_hold(TRAIN, DAY, "S1-01", "u1")
    assert result["seat_no"] == "S1-01"
    with db.get_pool().connection() as conn:
        seat = repository.list_seats(conn, TRAIN, DAY)[0]
        winners = conn.execute(
            "SELECT count(*) AS n FROM naive_bookings WHERE seat_id = %s",
            (seat["id"],),
        ).fetchone()["n"]
    assert seat["status"] == "booked"
    assert winners == 1


def test_naive_hold_rejects_unavailable_seat(monkeypatch):
    seed_one_seat()
    monkeypatch.setattr(service, "sleep", lambda _: None)
    with db.get_pool().connection() as conn:
        conn.execute("UPDATE seats SET status = 'booked'")
        conn.commit()
    with pytest.raises(SeatUnavailable):
        service.naive_hold(TRAIN, DAY, "S1-01", "u2")
