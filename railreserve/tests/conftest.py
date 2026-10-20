import os
from pathlib import Path

import psycopg
import pytest

from app import db

TEST_ADMIN_URL = os.getenv(
    "TEST_ADMIN_URL", "postgresql://rail:rail@postgres:5432/postgres"
)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://rail:rail@postgres:5432/railreserve_test"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SWEEPER_ENABLED"] = "false"
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    with psycopg.connect(TEST_ADMIN_URL, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS railreserve_test WITH (FORCE)")
        conn.execute("CREATE DATABASE railreserve_test")
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        schema = Path("db/init.sql").read_text()
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.commit()
    db.init_pool(TEST_DATABASE_URL, max_size=30)
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def clean_tables():
    with db.get_pool().connection() as conn:
        conn.execute(
            "TRUNCATE naive_bookings, payments, bookings, holds, seats "
            "RESTART IDENTITY CASCADE"
        )
        conn.execute("ALTER SEQUENCE pnr_seq RESTART WITH 1000000000")
        conn.commit()
    yield
