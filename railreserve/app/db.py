from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def init_pool(url: str, max_size: int = 20) -> None:
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=max_size,
        kwargs={"row_factory": dict_row},
        open=True,
    )


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool is not initialized")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
