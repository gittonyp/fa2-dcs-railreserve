from app.ratelimit import allow_hold


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True


def test_rate_limit_allows_within_limit_and_blocks_after():
    client = FakeRedis()
    assert allow_hold(client, "u1", 2) is True
    assert allow_hold(client, "u1", 2) is True
    assert allow_hold(client, "u1", 2) is False
