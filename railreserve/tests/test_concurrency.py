from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from app import db, repository, service
from app.errors import SeatUnavailable

TRAIN = "12951"
DAY = date(2026, 11, 1)


def seed_one_seat():
    with db.get_pool().connection() as conn:
        repository.reset_demo(conn, TRAIN, DAY, 1)
        conn.commit()


def test_safe_hold_allows_exactly_one_winner():
    seed_one_seat()

    def attempt(i: int) -> str:
        try:
            service.hold_seat(TRAIN, DAY, "S1-01", f"user-{i}")
            return "ok"
        except SeatUnavailable:
            return "rejected"

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))

    assert results.count("ok") == 1
    assert results.count("rejected") == 19
    with db.get_pool().connection() as conn:
        stats = repository.stats(conn, TRAIN, DAY)
    assert stats["held"] == 1


def test_naive_path_can_produce_multiple_winners(monkeypatch):
    seed_one_seat()
    barrier = Barrier(20)
    monkeypatch.setattr(service, "sleep", lambda _: barrier.wait(timeout=5))

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda i: service.naive_hold(TRAIN, DAY, "S1-01", f"u-{i}"), range(20)))

    with db.get_pool().connection() as conn:
        stats = repository.stats(conn, TRAIN, DAY)
    assert stats["naive_winners"] > 1
