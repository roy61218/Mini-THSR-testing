"""Initialize a new database from the CSV files in one transaction."""

import csv
from datetime import date, time, timedelta
import logging

from app.config import DATA_DIR, END_DATE, SCHEMA_FILE, START_DATE
from app.database import connect


def rows(filename, required):
    path = DATA_DIR / filename
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = tuple(value.strip() for value in next(reader, ()))
        if len(headers) != len(set(headers)) or set(headers) != set(required):
            raise ValueError(f"{filename}: expected columns {', '.join(required)}")
        records = []
        for values in reader:
            if not any(value.strip() for value in values):
                continue
            if len(values) != len(headers):
                raise ValueError(f"{filename}, line {reader.line_num}: wrong column count")
            records.append((reader.line_num, dict(zip(headers, map(str.strip, values)))))
        return records


def positive(value, label):
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def required_text(value, label):
    if not value or "\x00" in value:
        raise ValueError(f"{label} must be nonempty text")
    return value


def parse_time(value):
    if len(value) != 5 or value[2] != ":":
        raise ValueError("station times must use HH:MM")
    hours, minutes = value[:2], value[3:]
    if not (hours.isascii() and hours.isdecimal() and minutes.isascii() and minutes.isdecimal()):
        raise ValueError("station times must use HH:MM")
    return time(int(hours), int(minutes))


def read_dataset():
    users = []
    for line, row in rows("users.csv", ("user_id", "name", "phone")):
        users.append((
            required_text(row["user_id"], f"users.csv line {line}: user_id"),
            required_text(row["name"], f"users.csv line {line}: name"),
            row["phone"] or None,
        ))

    stations = []
    for line, row in rows("stations.csv", ("station_id", "name", "seq")):
        stations.append((
            required_text(row["station_id"], f"stations.csv line {line}: station_id"),
            required_text(row["name"], f"stations.csv line {line}: name"),
            positive(row["seq"], f"stations.csv line {line}: seq"),
        ))
    station_order = [station_id for station_id, _, _ in sorted(stations, key=lambda row: row[2])]
    if not users or len(station_order) < 2:
        raise ValueError("At least one user and two stations are required")

    trains, stops, seats, runs = [], [], [], []
    fields = ("train_no", "direction", "days", "cars", *station_order)
    days = [START_DATE + timedelta(days=i) for i in range((END_DATE - START_DATE).days + 1)]
    for line, row in rows("timetable.csv", fields):
        try:
            train_no = required_text(row["train_no"], "train_no")
            direction = row["direction"]
            if direction not in ("S", "N"):
                raise ValueError("direction must be S or N")
            weekdays = row["days"]
            if not weekdays or set(weekdays) - set("1234567") or len(weekdays) != len(set(weekdays)):
                raise ValueError("days must be distinct weekday digits 1 through 7")
            cars = positive(row["cars"], "cars")
            route = station_order if direction == "S" else station_order[::-1]
            train_stops = [(station_id, parse_time(row[station_id])) for station_id in route if row[station_id]]
            if len(train_stops) < 2:
                raise ValueError("a train must stop at two or more stations")
            if any(a[1] > b[1] for a, b in zip(train_stops, train_stops[1:])):
                raise ValueError("stop times must follow the direction of travel")
        except ValueError as error:
            raise ValueError(f"timetable.csv, line {line}: {error}") from error
        trains.append((train_no, direction, weekdays, cars))
        stops.extend((train_no, n, station_id, stop_time) for n, (station_id, stop_time) in enumerate(train_stops, 1))
        seats.extend((train_no, car, seat_row, letter) for car in range(1, cars + 1)
                     for seat_row in range(1, 5) for letter in "ABCDE")
        runs.extend((train_no, day) for day in days if str(day.isoweekday()) in weekdays)
    return users, stations, trains, stops, seats, runs


def initialize():
    with connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (20261201,))
        exists = conn.execute("SELECT to_regclass('public.reference_init') IS NOT NULL AS found").fetchone()
        if exists["found"]:
            version = conn.execute("SELECT schema_version FROM reference_init").fetchone()
            if version == {"schema_version": 1}:
                logging.info("Database already initialized; retained existing bookings.")
                return
            raise RuntimeError("The database has an unexpected reference schema version")
        data = read_dataset()
        conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        inserts = (
            "INSERT INTO users (user_id, name, phone) VALUES (%s, %s, %s)",
            "INSERT INTO stations (station_id, name, seq) VALUES (%s, %s, %s)",
            "INSERT INTO trains (train_no, direction, operating_days, cars) VALUES (%s, %s, %s, %s)",
            "INSERT INTO train_stops (train_no, stop_no, station_id, stop_time) VALUES (%s, %s, %s, %s)",
            "INSERT INTO train_seats (train_no, car_no, row_no, seat_letter) VALUES (%s, %s, %s, %s)",
            "INSERT INTO train_runs (train_no, service_date) VALUES (%s, %s)",
        )
        with conn.cursor() as cursor:
            for sql, records in zip(inserts, data):
                if records:
                    cursor.executemany(sql, records)
        conn.execute("INSERT INTO reference_init (schema_version) VALUES (1)")
    logging.info("Initialized %d users, %d stations, %d trains and %d dated runs.",
                 len(data[0]), len(data[1]), len(data[2]), len(data[5]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    initialize()
