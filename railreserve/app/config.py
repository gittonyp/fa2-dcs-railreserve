import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    hold_ttl_seconds: int
    naive_delay_ms: int
    sweeper_enabled: bool
    sweeper_interval_seconds: float
    rate_limit_per_minute: int


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://rail:rail@postgres:5432/railreserve"
        ),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        hold_ttl_seconds=int(os.getenv("HOLD_TTL_SECONDS", "300")),
        naive_delay_ms=int(os.getenv("NAIVE_DELAY_MS", "150")),
        sweeper_enabled=os.getenv("SWEEPER_ENABLED", "true").lower() == "true",
        sweeper_interval_seconds=float(os.getenv("SWEEPER_INTERVAL_SECONDS", "2")),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "120")),
    )
