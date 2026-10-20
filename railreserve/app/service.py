from datetime import date
from decimal import Decimal
from time import sleep
from uuid import UUID

from app import db, repository
from app.config import get_settings
from app.errors import SeatUnavailable


def reset_demo(train_id: str, journey_date: date, seat_count: int) -> list[dict]:
    with db.get_pool().connection() as conn:
        return repository.reset_demo(conn, train_id, journey_date, seat_count)


def hold_seat(
    train_id: str,
    journey_date: date,
    seat_no: str,
    user_id: str,
) -> dict:
    settings = get_settings()
    with db.get_pool().connection() as conn:
        repository.expire_stale(conn)
        result = repository.hold_seat(
            conn,
            train_id,
            journey_date,
            seat_no,
            user_id,
            settings.hold_ttl_seconds,
        )
    if result is None:
        raise SeatUnavailable
    return result


def pay_hold(
    hold_id: UUID,
    idempotency_key: str,
    amount: Decimal,
) -> dict:
    with db.get_pool().connection() as conn:
        return repository.pay_hold(conn, hold_id, idempotency_key, amount)


def get_booking(booking_id: UUID) -> dict | None:
    with db.get_pool().connection() as conn:
        return repository.get_booking(conn, booking_id)


def naive_hold(
    train_id: str,
    journey_date: date,
    seat_no: str,
    user_id: str,
) -> dict:
    settings = get_settings()
    with db.get_pool().connection() as conn:
        seat = repository.get_seat(conn, train_id, journey_date, seat_no)
    if seat is None or seat["status"] != "available":
        raise SeatUnavailable
    sleep(settings.naive_delay_ms / 1000)
    with db.get_pool().connection() as conn:
        repository.naive_book(conn, seat["id"], user_id)
    return {"seat_id": seat["id"], "seat_no": seat["seat_no"], "user_id": user_id}


def stats(train_id: str, journey_date: date) -> dict:
    with db.get_pool().connection() as conn:
        return repository.stats(conn, train_id, journey_date)


def expire_stale() -> None:
    with db.get_pool().connection() as conn:
        repository.expire_stale(conn)
