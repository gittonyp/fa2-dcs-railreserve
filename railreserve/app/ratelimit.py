import time

from redis.exceptions import RedisError


def allow_hold(client, user_id: str, limit: int, window_seconds: int = 60) -> bool:
    if client is None or limit <= 0:
        return True
    key = f"ratelimit:hold:{user_id}:{int(time.time() // window_seconds)}"
    try:
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_seconds)
        return count <= limit
    except RedisError:
        return True
