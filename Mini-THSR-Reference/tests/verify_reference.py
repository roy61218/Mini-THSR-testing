"""Run HTTP checks against an isolated, temporary PostgreSQL database.

Use the backend requirements and set DATABASE_URL to a test server whose
role can create databases. No data in the configured database is changed.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def fixtures(path):
    data = {
        "users.csv": [
            ("user_id", "name", "phone"), ("TEST01", "User One", ""), ("TEST02", "User Two", ""),
        ],
        "stations.csv": [
            ("station_id", "name", "seq"), ("SOUTH", "South", 40), ("MID", "Middle", 20),
            ("NORTH", "North", 10), ("GAP", "Other Stop", 30),
        ],
        "timetable.csv": [
            ("train_no", "direction", "days", "cars", "NORTH", "MID", "GAP", "SOUTH"),
            ("0001", "S", "1234567", 1, "06:00", "06:30", "", "07:00"),
            ("0002", "N", "12345", 2, "08:00", "07:30", "07:10", "07:00"),
            ("0003", "S", "12345", 1, "06:00", "", "06:45", "07:10"),
            ("0004", "S", "67", 1, "10:00", "10:30", "", "11:00"),
        ],
    }
    for name, records in data.items():
        with (Path(path) / name).open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(records)


class QuietRequests(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


@contextmanager
def serve(app):
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietRequests)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


class Client:
    def __init__(self, base_url):
        self.base_url = base_url

    def request(self, path, *, query=None, body=None, raw=None):
        if query is not None:
            path += "?" + urlencode(query)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = Request(self.base_url + path, data=data)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def get(self, path, query=None):
        status, data = self.request(path, query=query)
        assert status == 200, (path, status, data)
        return data

    def book(self, trip, count=1, user="TEST01", preference=None):
        return self.request("/bookings", body={
            **trip, "user_id": user, "seat_count": count, "preference": preference,
        })

    def cancel(self, booking, user=None):
        return self.request("/bookings/" + booking["booking_id"] + "/cancel",
                            body={"user_id": user or booking["user_id"]})


def route(day, start="NORTH", end="SOUTH", train="0001"):
    return {"date": day, "from_station_id": start, "to_station_id": end, "train_no": train}


def ok(result, expected):
    status, body = result
    assert status == expected, (status, body)
    return body


def error(result, status, code):
    result_body = ok(result, status)
    assert result_body["error"]["code"] == code, result_body


def check_count(client, trip, expected):
    data = client.get("/seats", trip)
    assert data["available_seat_count"] == len(data["seats"]) == expected, data
    assert len({seat["seat_id"] for seat in data["seats"]}) == expected
    return data["seats"]


def concurrent(*calls):
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=5)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [future.result(timeout=12) for future in [pool.submit(run, call) for call in calls]]


def verify(client):
    assert client.get("/users") == [
        {"user_id": "TEST01", "name": "User One"}, {"user_id": "TEST02", "name": "User Two"},
    ]
    assert [s["station_id"] for s in client.get("/stations")] == ["NORTH", "MID", "GAP", "SOUTH"]
    assert [t["train_no"] for t in client.get("/schedules", route("2026-12-07"))] == ["0001", "0003"]
    assert [t["train_no"] for t in client.get("/schedules", route("2026-12-12"))] == ["0001", "0004"]
    time_match = client.get("/schedules", {
        **route("2026-12-07", "MID"), "departure_time_from": "06:30", "departure_time_to": "06:30",
    })
    assert [(t["train_no"], t["departure_time"]) for t in time_match] == [("0001", "06:30")]
    northbound = route("2026-12-07", "SOUTH", "NORTH", "0002")
    assert [t["train_no"] for t in client.get("/schedules", northbound)] == ["0002"]
    check_count(client, northbound, 40)
    print("PASS: CSV import, station order, dates, route direction, and schedule ordering")

    error(client.request("/seats", query=route("2026-12-12", "SOUTH", "NORTH", "0002")), 404, "NOT_FOUND")
    error(client.request("/seats", query=route("2026-12-07", "NORTH", "MID", "0003")), 422, "INVALID_PARAMETER")
    error(client.request("/seats", query=route("2026-12-07", "SOUTH", "NORTH")), 422, "INVALID_PARAMETER")
    error(client.request("/bookings", raw=b"{"), 400, "INVALID_JSON")
    error(client.request("/bookings", body=["not", "an", "object"]), 422, "INVALID_PARAMETER")
    error(client.request("/bookings", query={"user_id": "absent"}), 422, "INVALID_PARAMETER")
    error(client.request("/schedules", query=route("2026-11-30")), 422, "INVALID_PARAMETER")
    for count in [0, 6, True, 1.5, "1"]:
        error(client.book(route("2026-12-07"), count=count), 422, "INVALID_PARAMETER")
    error(client.book(route("2026-12-07"), count=2, preference="window"), 422, "INVALID_PARAMETER")
    error(client.book(route("2026-12-07"), preference="middle"), 422, "INVALID_PARAMETER")
    print("PASS: invalid JSON, dates, train operation, stations, users, and seat options")

    first_leg = route("2026-12-07", "NORTH", "MID")
    second_leg = route("2026-12-07", "MID", "SOUTH")
    first = ok(client.book(first_leg, preference="window"), 201)
    check_count(client, first_leg, 19)
    check_count(client, second_leg, 20)
    second = ok(client.book(second_leg, user="TEST02", preference="window"), 201)
    assert first["seats"] == second["seats"]  # Both legs can use the first legal seat.
    check_count(client, route("2026-12-07"), 19)
    check_count(client, route("2026-12-08"), 20)
    assert client.get("/bookings", {"user_id": "TEST02", "booking_id": first["booking_id"]}) == []
    error(client.cancel(first, "TEST02"), 404, "NOT_FOUND")
    cancelled = ok(client.cancel(first), 200)
    assert cancelled["status"] == "cancelled" and cancelled["seats"] == first["seats"]
    assert client.get("/bookings", {"user_id": "TEST01", "booking_id": first["booking_id"]}) == [cancelled]
    check_count(client, first_leg, 20)
    check_count(client, second_leg, 19)
    error(client.cancel(first), 409, "ALREADY_CANCELLED")
    print("PASS: half-open intervals, date isolation, ownership, cancellation, and history")

    preferred = route("2026-12-08")
    for _ in range(8):
        booking = ok(client.book(preferred, preference="window"), 201)
        assert booking["seats"][0]["seat_letter"] in "AE" and booking["preference_met"] is True
    check_count(client, preferred, 12)
    error(client.book(preferred, preference="window"), 409, "NO_PREFERENCE")
    for _ in range(8):
        booking = ok(client.book(preferred, preference="aisle"), 201)
        assert booking["seats"][0]["seat_letter"] in "CD" and booking["preference_met"] is True
    assert all(s["seat_letter"] == "B" for s in check_count(client, preferred, 4))
    before = client.get("/bookings", {"user_id": "TEST01"})
    error(client.book(preferred, count=2), 409, "NO_ADJACENT_SEATS")
    assert client.get("/bookings", {"user_id": "TEST01"}) == before
    check_count(client, preferred, 4)
    print("PASS: seat preferences and rejection of fragmented availability")

    adjacency = route("2026-12-09")
    ok(client.book(adjacency, count=2), 201)
    crossing = ok(client.book(adjacency, count=2), 201)
    assert [s["seat_letter"] for s in crossing["seats"]] == ["C", "D"]
    assert crossing["adjacent_met"] is True and crossing["preference_met"] is None
    five = ok(client.book(adjacency, count=5), 201)
    assert len({(s["car_no"], s["row_no"]) for s in five["seats"]}) == 1
    assert [s["seat_letter"] for s in five["seats"]] == list("ABCDE")
    print("PASS: adjacent groups of two and five, including C-D across the aisle")

    final_seat = route("2026-12-10")
    for count in [5, 5, 5, 4]:
        ok(client.book(final_seat, count=count), 201)
    check_count(client, final_seat, 1)
    before = client.get("/bookings", {"user_id": "TEST01"})
    error(client.book(final_seat, count=2), 409, "NO_SEAT")
    assert client.get("/bookings", {"user_id": "TEST01"}) == before
    results = concurrent(lambda: client.book(final_seat), lambda: client.book(final_seat, user="TEST02"))
    assert sorted(status for status, _ in results) == [201, 409], results
    error(next(result for result in results if result[0] == 409), 409, "NO_SEAT")
    check_count(client, final_seat, 0)
    assert next(t for t in client.get("/schedules", final_seat) if t["train_no"] == "0001")["remain_seats"] == 0
    print("PASS: atomic failure and two requests for the last seat; sold-out trains remain visible")

    multi = route("2026-12-11")
    for count in [5, 5, 5, 1]:
        ok(client.book(multi, count=count), 201)
    check_count(client, multi, 4)
    results = concurrent(lambda: client.book(multi, count=3), lambda: client.book(multi, count=3, user="TEST02"))
    assert sorted(status for status, _ in results) == [201, 409], results
    error(next(result for result in results if result[0] == 409), 409, "NO_SEAT")
    winner = next(body for status, body in results if status == 201)
    assert winner["seat_count"] == len(winner["seats"]) == 3
    check_count(client, multi, 1)
    both = concurrent(lambda: client.cancel(winner), lambda: client.cancel(winner))
    assert sorted(status for status, _ in both) == [200, 409], both
    error(next(result for result in both if result[0] == 409), 409, "ALREADY_CANCELLED")
    check_count(client, multi, 4)
    print("PASS: concurrent multi-ticket booking and concurrent repeated cancellation")
    return cancelled


def main():
    admin_url = os.environ["DATABASE_URL"]
    name = "minithsr_verify_" + uuid4().hex[:12]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with TemporaryDirectory(prefix="minithsr-fixtures-") as path:
                fixtures(path)
                os.environ["DATABASE_URL"] = make_conninfo(admin_url, dbname=name)
                os.environ["DATA_DIR"] = path
                from app import create_app
                from db_init import initialize
                initialize()
                with serve(create_app()) as base:
                    cancelled = verify(Client(base))
                initialize()
                with serve(create_app()) as base:
                    assert Client(base).get("/bookings", {
                        "user_id": cancelled["user_id"], "booking_id": cancelled["booking_id"],
                    }) == [cancelled]
                print("PASS: re-initialization and backend restart preserve order history")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    print("All reference checks passed.")


if __name__ == "__main__":
    main()
