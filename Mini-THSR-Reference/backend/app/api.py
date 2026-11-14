"""The seven HTTP endpoints in the course API contract."""

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest

from . import repository as repo
from . import service, validation
from .database import connect
from .errors import ApiError, invalid

api = Blueprint("rail", __name__)


def json_object():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        raise ApiError(400, "INVALID_JSON", "The request body must be valid JSON.") from None
    if not isinstance(data, dict):
        raise invalid("The request body must be a JSON object.")
    return data


@api.get("/users")
def list_users():
    with connect() as conn:
        return jsonify(repo.users(conn))


@api.get("/stations")
def list_stations():
    with connect() as conn:
        return jsonify(repo.stations(conn))


@api.get("/schedules")
def list_schedules():
    day = validation.service_date(request.args)
    origin, destination = validation.route_stations(request.args)
    earliest = validation.optional_time(request.args, "departure_time_from")
    latest = validation.optional_time(request.args, "departure_time_to")
    if earliest is not None and latest is not None and earliest > latest:
        raise invalid("The earliest departure time must not exceed the latest.")
    with connect() as conn:
        if not repo.stations_exist(conn, origin, destination):
            raise invalid("The specified departure or arrival station does not exist.")
        rows = repo.schedules(conn, day, origin, destination, earliest, latest)
        return jsonify([service.schedule_payload(row) for row in rows])


@api.get("/seats")
def list_seats():
    trip = validation.trip_fields(request.args)
    with connect() as conn:
        route = service.require_route(conn, trip)
        seats = repo.available_seats(conn, trip, route)
        return jsonify(available_seat_count=len(seats), seats=seats)


@api.post("/bookings")
def create_booking():
    data = json_object()
    user_id = validation.text_field(data, "user_id")
    trip = validation.trip_fields(data)
    count, preference = validation.booking_options(data)
    with connect() as conn:
        result = service.create_booking(conn, trip, user_id, count, preference)
    return jsonify(result), 201


@api.get("/bookings")
def list_bookings():
    user_id = validation.text_field(request.args, "user_id")
    booking_id = (validation.text_field(request.args, "booking_id")
                  if "booking_id" in request.args else None)
    with connect() as conn:
        service.require_user(conn, user_id)
        return jsonify([service.booking_payload(row) for row in repo.bookings(conn, user_id, booking_id)])


@api.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id = validation.text_field(json_object(), "user_id")
    booking_id = validation.text_field({"booking_id": booking_id}, "booking_id")
    with connect() as conn:
        result = service.cancel_booking(conn, user_id, booking_id)
    return jsonify(result)
