import logging
import threading
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from redis import Redis

from app import db, ratelimit, repository, service
from app.config import get_settings
from app.errors import HoldExpired, HoldNotFound, SeatUnavailable
from app.schemas import HoldRequest, PayRequest, ResetRequest

log = logging.getLogger(__name__)


def sweeper_loop(interval: float, stop_event: threading.Event) -> None:
    while not stop_event.wait(interval):
        try:
            service.expire_stale()
        except Exception:
            log.exception("expiry sweeper failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_pool(settings.database_url)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    stop_event = threading.Event()
    thread = None
    if settings.sweeper_enabled:
        thread = threading.Thread(
            target=sweeper_loop,
            args=(settings.sweeper_interval_seconds, stop_event),
            daemon=True,
        )
        thread.start()
    yield
    stop_event.set()
    if thread is not None:
        thread.join(timeout=2)
    db.close_pool()


app = FastAPI(title="RailReserve", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/demo/reset")
def reset_demo(payload: ResetRequest) -> dict:
    seats = service.reset_demo(
        payload.train_id, payload.journey_date, payload.seat_count
    )
    return {"seats": seats}


@app.get("/api/seats")
def seats(
    train_id: str = Query(...),
    journey_date: date = Query(...),
) -> dict:
    with db.get_pool().connection() as conn:
        rows = repository.list_seats(conn, train_id, journey_date)
    return {"seats": rows}


@app.post("/api/bookings/hold", status_code=201)
def hold(payload: HoldRequest) -> dict:
    settings = get_settings()
    client = getattr(app.state, "redis", None)
    if not ratelimit.allow_hold(
        client, payload.user_id, settings.rate_limit_per_minute
    ):
        raise HTTPException(status_code=429, detail="rate_limited")
    try:
        return service.hold_seat(
            payload.train_id,
            payload.journey_date,
            payload.seat_no,
            payload.user_id,
        )
    except SeatUnavailable:
        raise HTTPException(status_code=409, detail="seat_unavailable")


@app.post("/api/bookings/{hold_id}/pay")
def pay(hold_id: UUID, payload: PayRequest) -> dict:
    try:
        return service.pay_hold(hold_id, payload.idempotency_key, payload.amount)
    except HoldNotFound:
        raise HTTPException(status_code=404, detail="hold_not_found")
    except HoldExpired:
        raise HTTPException(status_code=410, detail="hold_expired")


@app.get("/api/bookings/{booking_id}")
def booking(booking_id: UUID) -> dict:
    result = service.get_booking(booking_id)
    if result is None:
        raise HTTPException(status_code=404, detail="booking_not_found")
    return result


@app.post("/api/naive/hold", status_code=201)
def naive_hold(payload: HoldRequest) -> dict:
    try:
        return service.naive_hold(
            payload.train_id,
            payload.journey_date,
            payload.seat_no,
            payload.user_id,
        )
    except SeatUnavailable:
        raise HTTPException(status_code=409, detail="seat_unavailable")


@app.get("/api/stats")
def stats(
    train_id: str = Query(...),
    journey_date: date = Query(...),
) -> dict:
    return service.stats(train_id, journey_date)
