CREATE TABLE users (
    user_id text PRIMARY KEY CHECK (btrim(user_id) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    phone text
);

CREATE TABLE stations (
    station_id text PRIMARY KEY CHECK (btrim(station_id) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    seq integer NOT NULL UNIQUE CHECK (seq > 0)
);

CREATE TABLE trains (
    train_no text PRIMARY KEY CHECK (btrim(train_no) <> ''),
    direction char(1) NOT NULL CHECK (direction IN ('N', 'S')),
    operating_days text NOT NULL CHECK (operating_days ~ '^[1-7]{1,7}$'),
    cars integer NOT NULL CHECK (cars > 0)
);

-- Stop numbers follow this train's travel direction, including northbound trips.
CREATE TABLE train_stops (
    train_no text NOT NULL REFERENCES trains,
    stop_no integer NOT NULL CHECK (stop_no > 0),
    station_id text NOT NULL REFERENCES stations,
    stop_time time NOT NULL,
    PRIMARY KEY (train_no, stop_no),
    UNIQUE (train_no, station_id)
);

CREATE TABLE train_seats (
    train_no text NOT NULL REFERENCES trains,
    car_no integer NOT NULL CHECK (car_no > 0),
    row_no smallint NOT NULL CHECK (row_no BETWEEN 1 AND 4),
    seat_letter char(1) NOT NULL CHECK (seat_letter IN ('A', 'B', 'C', 'D', 'E')),
    PRIMARY KEY (train_no, car_no, row_no, seat_letter)
);

-- One row per actual run, also used as the booking/cancellation lock target.
CREATE TABLE train_runs (
    train_no text NOT NULL REFERENCES trains,
    service_date date NOT NULL,
    PRIMARY KEY (train_no, service_date)
);
CREATE INDEX train_runs_by_date ON train_runs (service_date, train_no);

CREATE SEQUENCE booking_number_seq;
CREATE TABLE bookings (
    booking_id text PRIMARY KEY DEFAULT ('B' || nextval('booking_number_seq')::text),
    user_id text NOT NULL REFERENCES users,
    train_no text NOT NULL,
    service_date date NOT NULL,
    from_stop integer NOT NULL,
    to_stop integer NOT NULL,
    seat_count smallint NOT NULL CHECK (seat_count BETWEEN 1 AND 5),
    preference text CHECK (preference IN ('window', 'aisle')),
    status text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_at timestamptz,
    FOREIGN KEY (train_no, service_date) REFERENCES train_runs,
    FOREIGN KEY (train_no, from_stop) REFERENCES train_stops,
    FOREIGN KEY (train_no, to_stop) REFERENCES train_stops,
    UNIQUE (booking_id, train_no),
    CHECK (from_stop < to_stop),
    CHECK (seat_count = 1 OR preference IS NULL),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);
ALTER SEQUENCE booking_number_seq OWNED BY bookings.booking_id;
CREATE INDEX bookings_by_user ON bookings (user_id, created_at, booking_id);
CREATE INDEX active_bookings_by_run
    ON bookings (train_no, service_date, from_stop, to_stop)
    WHERE status = 'confirmed';

CREATE TABLE tickets (
    booking_id text NOT NULL,
    train_no text NOT NULL,
    car_no integer NOT NULL,
    row_no smallint NOT NULL,
    seat_letter char(1) NOT NULL,
    PRIMARY KEY (booking_id, car_no, row_no, seat_letter),
    FOREIGN KEY (booking_id, train_no) REFERENCES bookings (booking_id, train_no),
    FOREIGN KEY (train_no, car_no, row_no, seat_letter) REFERENCES train_seats
);

-- Cancelled tickets remain available for order history but no longer block seats.
CREATE VIEW active_tickets AS
    SELECT b.train_no, b.service_date, b.from_stop, b.to_stop,
           t.car_no, t.row_no, t.seat_letter
    FROM bookings AS b
    JOIN tickets AS t USING (booking_id, train_no)
    WHERE b.status = 'confirmed';

CREATE TABLE reference_init (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    schema_version integer NOT NULL CHECK (schema_version > 0)
);
