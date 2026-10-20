class SeatUnavailable(Exception):
    pass


class HoldNotFound(Exception):
    pass


class HoldExpired(Exception):
    pass


class IdempotencyKeyReused(Exception):
    pass
