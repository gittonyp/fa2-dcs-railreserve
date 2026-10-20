CREATE TABLE seats (
    id SERIAL PRIMARY KEY,
    train_id TEXT NOT NULL,
    journey_date DATE NOT NULL,
    seat_no TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'held', 'booked')),
    hold_id UUID,
    hold_expires_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 0,
    UNIQUE (train_id, journey_date, seat_no)
);

CREATE TABLE holds (
    id UUID PRIMARY KEY,
    seat_id INTEGER NOT NULL REFERENCES seats(id),
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paid', 'expired', 'cancelled')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_active_hold_per_seat
    ON holds (seat_id) WHERE status = 'active';

CREATE TABLE bookings (
    id UUID PRIMARY KEY,
    hold_id UUID NOT NULL UNIQUE REFERENCES holds(id),
    seat_id INTEGER NOT NULL UNIQUE REFERENCES seats(id),
    user_id TEXT NOT NULL,
    pnr TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'confirmed',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE payments (
    id UUID PRIMARY KEY,
    booking_id UUID NOT NULL REFERENCES bookings(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'captured',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE naive_bookings (
    id UUID PRIMARY KEY,
    seat_id INTEGER NOT NULL REFERENCES seats(id),
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE pnr_seq START WITH 1000000000;
