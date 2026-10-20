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
