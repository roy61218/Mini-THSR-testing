"""Parameterized SQL for the rail network, seat inventory, and orders."""


def users(conn):
    return conn.execute("SELECT user_id, name FROM users ORDER BY user_id").fetchall()


def stations(conn):
    return conn.execute("SELECT station_id, name FROM stations ORDER BY seq").fetchall()


def user_exists(conn, user_id):
    return conn.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,)).fetchone() is not None


def stations_exist(conn, origin, destination):
    row = conn.execute(
        "SELECT count(*) AS n FROM stations WHERE station_id IN (%s, %s)",
        (origin, destination),
    ).fetchone()
    return row["n"] == 2


def find_run(conn, train_no, service_date, *, lock=False):
    sql = "SELECT 1 FROM train_runs WHERE train_no = %s AND service_date = %s"
    if lock:
        sql += " FOR UPDATE"
    return conn.execute(sql, (train_no, service_date)).fetchone() is not None


def find_route(conn, trip):
    return conn.execute("""
        SELECT a.stop_no AS from_stop, z.stop_no AS to_stop,
               a.stop_time AS departure_time, z.stop_time AS arrival_time
        FROM train_stops AS a
        JOIN train_stops AS z ON z.train_no = a.train_no
        WHERE a.train_no = %s AND a.station_id = %s AND z.station_id = %s
          AND a.stop_no < z.stop_no
    """, (trip.train_no, trip.from_station_id, trip.to_station_id)).fetchone()


# The same half-open interval predicate is used by both schedule counts and seat lookup.
# All aliases here are static SQL; every external value is passed as a parameter.
FREE_SEAT = """
    NOT EXISTS (
        SELECT 1
        FROM active_tickets AS sold
        WHERE sold.train_no = seat.train_no
          AND sold.service_date = route.service_date
          AND sold.car_no = seat.car_no AND sold.row_no = seat.row_no
          AND sold.seat_letter = seat.seat_letter
          AND sold.from_stop < route.to_stop AND route.from_stop < sold.to_stop
    )
"""


def schedules(conn, service_date, origin, destination, earliest, latest):
    return conn.execute(f"""
        WITH route AS (
            SELECT run.train_no, run.service_date,
                   a.stop_no AS from_stop, z.stop_no AS to_stop,
                   a.stop_time AS departure_time, z.stop_time AS arrival_time
            FROM train_runs AS run
            JOIN train_stops AS a ON a.train_no = run.train_no AND a.station_id = %s
            JOIN train_stops AS z ON z.train_no = run.train_no AND z.station_id = %s
            WHERE run.service_date = %s
              AND a.stop_no < z.stop_no
              AND a.stop_time >= COALESCE(%s::time, a.stop_time)
              AND a.stop_time <= COALESCE(%s::time, a.stop_time)
        )
        SELECT route.train_no, route.service_date, route.departure_time, route.arrival_time,
               (SELECT count(*) FROM train_seats AS seat
                WHERE seat.train_no = route.train_no AND {FREE_SEAT}) AS remain_seats
        FROM route
        ORDER BY route.departure_time, route.train_no
    """, (origin, destination, service_date, earliest, latest)).fetchall()


def available_seats(conn, trip, route):
    return conn.execute(f"""
        WITH route (train_no, service_date, from_stop, to_stop) AS (
            VALUES (%s::text, %s::date, %s::integer, %s::integer)
        )
        SELECT seat.car_no, seat.row_no, seat.seat_letter,
               seat.car_no || '-' || seat.row_no || seat.seat_letter AS seat_id
        FROM route
        JOIN train_seats AS seat ON seat.train_no = route.train_no
        WHERE {FREE_SEAT}
        ORDER BY seat.car_no, seat.row_no, seat.seat_letter
    """, (trip.train_no, trip.service_date, route["from_stop"], route["to_stop"])).fetchall()


def insert_booking(conn, trip, route, user_id, seats, preference):
    booking_id = conn.execute("""
        INSERT INTO bookings (user_id, train_no, service_date, from_stop, to_stop, seat_count, preference)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING booking_id
    """, (user_id, trip.train_no, trip.service_date, route["from_stop"], route["to_stop"],
          len(seats), preference)).fetchone()["booking_id"]
    with conn.cursor() as cursor:
        cursor.executemany("""
            INSERT INTO tickets (booking_id, train_no, car_no, row_no, seat_letter)
            VALUES (%s, %s, %s, %s, %s)
        """, [(booking_id, trip.train_no, s["car_no"], s["row_no"], s["seat_letter"]) for s in seats])
    return booking_id


def bookings(conn, user_id, booking_id=None):
    sql = """
        SELECT b.booking_id, b.user_id, b.train_no, b.service_date,
               a.station_id AS from_station_id, z.station_id AS to_station_id,
               a.stop_time AS departure_time, z.stop_time AS arrival_time,
               b.seat_count, b.preference, b.status,
               COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'seat_id', t.car_no || '-' || t.row_no || t.seat_letter,
                       'car_no', t.car_no, 'row_no', t.row_no, 'seat_letter', t.seat_letter
                   ) ORDER BY t.car_no, t.row_no, t.seat_letter)
                   FROM tickets AS t WHERE t.booking_id = b.booking_id
               ), '[]'::jsonb) AS seats
        FROM bookings AS b
        JOIN train_stops AS a ON a.train_no = b.train_no AND a.stop_no = b.from_stop
        JOIN train_stops AS z ON z.train_no = b.train_no AND z.stop_no = b.to_stop
        WHERE b.user_id = %s
    """
    params = [user_id]
    if booking_id is not None:
        sql += " AND b.booking_id = %s"
        params.append(booking_id)
    return conn.execute(sql + " ORDER BY b.created_at, b.booking_id", params).fetchall()


def booking_run(conn, user_id, booking_id):
    return conn.execute("""
        SELECT train_no, service_date FROM bookings WHERE booking_id = %s AND user_id = %s
    """, (booking_id, user_id)).fetchone()


def mark_cancelled(conn, user_id, booking_id):
    return conn.execute("""
        UPDATE bookings SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP
        WHERE booking_id = %s AND user_id = %s AND status = 'confirmed'
        RETURNING booking_id
    """, (booking_id, user_id)).fetchone()
