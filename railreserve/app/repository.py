from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg

from app.errors import HoldExpired, HoldNotFound

Connection = psycopg.Connection


def reset_demo(
    conn: Connection,
    train_id: str,
    journey_date: date,
    seat_count: int,
) -> list[dict[str, Any]]:
    with conn.transaction():
        conn.execute(
            "TRUNCATE naive_bookings, payments, bookings, holds, seats "
            "RESTART IDENTITY CASCADE"
        )
        conn.execute("ALTER SEQUENCE pnr_seq RESTART WITH 1000000000")
        rows = conn.execute(
            """
            INSERT INTO seats (train_id, journey_date, seat_no)
            SELECT %s, %s, 'S1-' || lpad(gs::text, 2, '0')
            FROM generate_series(1, %s) AS gs
            RETURNING id, seat_no, status
            """,
            (train_id, journey_date, seat_count),
        ).fetchall()
    return rows


def list_seats(
    conn: Connection,
    train_id: str,
    journey_date: date,
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, seat_no, status, hold_expires_at
        FROM seats
        WHERE train_id = %s AND journey_date = %s
        ORDER BY seat_no
        """,
        (train_id, journey_date),
    ).fetchall()


def expire_stale(conn: Connection) -> None:
    with conn.transaction():
        conn.execute(
            """
            UPDATE holds SET status = 'expired'
            WHERE status = 'active' AND expires_at < now()
            """
        )
        conn.execute(
            """
            UPDATE seats
            SET status = 'available', hold_id = NULL, hold_expires_at = NULL
            WHERE status = 'held' AND hold_expires_at < now()
            """
        )


def hold_seat(
    conn: Connection,
    train_id: str,
    journey_date: date,
    seat_no: str,
    user_id: str,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    hold_id = uuid4()
    with conn.transaction():
        conn.execute(
            """
            UPDATE holds h SET status = 'expired'
            FROM seats s
            WHERE h.seat_id = s.id
              AND h.status = 'active'
              AND h.expires_at < now()
              AND s.train_id = %s
              AND s.journey_date = %s
              AND s.seat_no = %s
            """,
            (train_id, journey_date, seat_no),
        )
        row = conn.execute(
            """
            UPDATE seats
            SET status = 'held',
                hold_id = %s,
                hold_expires_at = now() + make_interval(secs => %s),
                version = version + 1
            WHERE train_id = %s
              AND journey_date = %s
              AND seat_no = %s
              AND (status = 'available'
                   OR (status = 'held' AND hold_expires_at < now()))
            RETURNING id, seat_no, hold_expires_at
            """,
            (hold_id, ttl_seconds, train_id, journey_date, seat_no),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            INSERT INTO holds (id, seat_id, user_id, status, expires_at)
            VALUES (%s, %s, %s, 'active', %s)
            """,
            (hold_id, row["id"], user_id, row["hold_expires_at"]),
        )
    return {
        "hold_id": hold_id,
        "seat_id": row["id"],
        "seat_no": row["seat_no"],
        "expires_at": row["hold_expires_at"],
    }


def pay_hold(
    conn: Connection,
    hold_id: UUID,
    idempotency_key: str,
    amount: Decimal,
) -> dict[str, Any]:
    with conn.transaction():
        existing = conn.execute(
            """
            SELECT b.id, b.pnr, b.status, s.seat_no
            FROM bookings b JOIN seats s ON s.id = b.seat_id
            WHERE b.idempotency_key = %s
            """,
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return {
                "booking_id": existing["id"],
                "pnr": existing["pnr"],
                "status": existing["status"],
                "seat_no": existing["seat_no"],
                "replayed": True,
            }

        hold = conn.execute(
            """
            SELECT id, seat_id, user_id, status, (expires_at < now()) AS is_expired
            FROM holds
            WHERE id = %s
            """,
            (hold_id,),
        ).fetchone()
        if hold is None:
            raise HoldNotFound

        if hold["status"] == "paid":
            existing = conn.execute(
                """
                SELECT b.id, b.pnr, b.status, s.seat_no
                FROM bookings b JOIN seats s ON s.id = b.seat_id
                WHERE b.hold_id = %s
                """,
                (hold_id,),
            ).fetchone()
            if existing is None:
                raise HoldNotFound
            return {
                "booking_id": existing["id"],
                "pnr": existing["pnr"],
                "status": existing["status"],
                "seat_no": existing["seat_no"],
                "replayed": True,
            }

        if hold["status"] != "active" or hold["is_expired"]:
            raise HoldExpired

        seat = conn.execute(
            """
            SELECT id, seat_no, status, hold_id
            FROM seats
            WHERE id = %s
            FOR UPDATE
            """,
            (hold["seat_id"],),
        ).fetchone()
        if (
            seat is None
            or seat["status"] != "held"
            or seat["hold_id"] != hold_id
        ):
            existing = conn.execute(
                """
                SELECT b.id, b.pnr, b.status, s.seat_no
                FROM bookings b JOIN seats s ON s.id = b.seat_id
                WHERE b.idempotency_key = %s OR b.hold_id = %s
                """,
                (idempotency_key, hold_id),
            ).fetchone()
            if existing is not None:
                return {
                    "booking_id": existing["id"],
                    "pnr": existing["pnr"],
                    "status": existing["status"],
                    "seat_no": existing["seat_no"],
                    "replayed": True,
                }
            raise HoldExpired

        booking_id = uuid4()
        pnr = conn.execute("SELECT 'PNR' || nextval('pnr_seq') AS pnr").fetchone()[
            "pnr"
        ]
        conn.execute(
            """
            INSERT INTO bookings
                (id, hold_id, seat_id, user_id, pnr, status, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, 'confirmed', %s)
            """,
            (
                booking_id,
                hold_id,
                seat["id"],
                hold["user_id"],
                pnr,
                idempotency_key,
            ),
        )
        conn.execute(
            """
            INSERT INTO payments
                (id, booking_id, idempotency_key, amount, status)
            VALUES (%s, %s, %s, %s, 'captured')
            """,
            (uuid4(), booking_id, idempotency_key, amount),
        )
        conn.execute(
            """
            UPDATE seats
            SET status = 'booked', hold_expires_at = NULL, version = version + 1
            WHERE id = %s
            """,
            (seat["id"],),
        )
        conn.execute(
            "UPDATE holds SET status = 'paid' WHERE id = %s",
            (hold_id,),
        )
    return {
        "booking_id": booking_id,
        "pnr": pnr,
        "status": "confirmed",
        "seat_no": seat["seat_no"],
        "replayed": False,
    }


def get_booking(conn: Connection, booking_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT b.id AS booking_id, b.pnr, b.status, s.seat_no, b.created_at
        FROM bookings b JOIN seats s ON s.id = b.seat_id
        WHERE b.id = %s
        """,
        (booking_id,),
    ).fetchone()


def get_seat(
    conn: Connection,
    train_id: str,
    journey_date: date,
    seat_no: str,
) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, seat_no, status
        FROM seats
        WHERE train_id = %s AND journey_date = %s AND seat_no = %s
        """,
        (train_id, journey_date, seat_no),
    ).fetchone()


def naive_book(
    conn: Connection,
    seat_id: int,
    user_id: str,
) -> None:
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO naive_bookings (id, seat_id, user_id)
            VALUES (%s, %s, %s)
            """,
            (uuid4(), seat_id, user_id),
        )
        conn.execute(
            "UPDATE seats SET status = 'booked' WHERE id = %s",
            (seat_id,),
        )


def stats(
    conn: Connection,
    train_id: str,
    journey_date: date,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, count(*) AS n
        FROM seats
        WHERE train_id = %s AND journey_date = %s
        GROUP BY status
        """,
        (train_id, journey_date),
    ).fetchall()
    counts = {"available": 0, "held": 0, "booked": 0}
    for row in rows:
        counts[row["status"]] = row["n"]
    counts["naive_winners"] = conn.execute(
        """
        SELECT count(*) AS n
        FROM naive_bookings nb JOIN seats s ON s.id = nb.seat_id
        WHERE s.train_id = %s AND s.journey_date = %s
        """,
        (train_id, journey_date),
    ).fetchone()["n"]
    counts["safe_bookings"] = conn.execute(
        """
        SELECT count(*) AS n
        FROM bookings b JOIN seats s ON s.id = b.seat_id
        WHERE s.train_id = %s AND s.journey_date = %s
        """,
        (train_id, journey_date),
    ).fetchone()["n"]
    return counts
