"""Seat allocation and order transactions."""

from . import repository as repo
from .errors import ApiError, invalid, not_found
from .validation import PREFERENCES


def require_user(conn, user_id):
    if not repo.user_exists(conn, user_id):
        raise invalid("The specified user does not exist.")


def require_route(conn, trip, *, lock=False):
    if not repo.find_run(conn, trip.train_no, trip.service_date, lock=lock):
        raise not_found("This train does not operate on the specified date.")
    route = repo.find_route(conn, trip)
    if route is None:
        raise invalid("The train must stop at the departure and arrival stations in order.")
    return route


def choose_seats(available, count, preference):
    if len(available) < count:
        raise ApiError(409, "NO_SEAT", "There are not enough seats for this trip.")
    if count == 1:
        if preference is None:
            return available[:1]
        for seat in available:
            if seat["seat_letter"] in PREFERENCES[preference]:
                return [seat]
        raise ApiError(409, "NO_PREFERENCE", "No available seat matches the preference.")

    # Available seats are ordered by carriage, row, and letter. C and D are adjacent.
    for i in range(len(available) - count + 1):
        group = available[i:i + count]
        first = group[0]
        if all(
            seat["car_no"] == first["car_no"] and seat["row_no"] == first["row_no"]
            and ord(seat["seat_letter"]) == ord(first["seat_letter"]) + offset
            for offset, seat in enumerate(group)
        ):
            return group
    raise ApiError(409, "NO_ADJACENT_SEATS", "No available group of adjacent seats fits the booking.")


def schedule_payload(row):
    return {
        "train_no": row["train_no"],
        "date": row["service_date"].isoformat(),
        "departure_time": row["departure_time"].isoformat(timespec="minutes"),
        "arrival_time": row["arrival_time"].isoformat(timespec="minutes"),
        "remain_seats": row["remain_seats"],
    }


def booking_payload(row):
    return {
        "booking_id": row["booking_id"],
        "user_id": row["user_id"],
        "train_no": row["train_no"],
        "date": row["service_date"].isoformat(),
        "from_station_id": row["from_station_id"],
        "to_station_id": row["to_station_id"],
        "departure_time": row["departure_time"].isoformat(timespec="minutes"),
        "arrival_time": row["arrival_time"].isoformat(timespec="minutes"),
        "seat_count": row["seat_count"],
        "seats": row["seats"],
        "preference": row["preference"],
        "preference_met": None if row["preference"] is None else True,
        "adjacent_met": None if row["seat_count"] == 1 else True,
        "status": row["status"],
    }


def create_booking(conn, trip, user_id, count, preference):
    with conn.transaction():
        require_user(conn, user_id)
        # Acquire the run lock before reading availability. Another writer may have
        # committed while this request waited, so availability is a separate statement.
        route = require_route(conn, trip, lock=True)
        available = repo.available_seats(conn, trip, route)
        chosen = choose_seats(available, count, preference)
        booking_id = repo.insert_booking(conn, trip, route, user_id, chosen, preference)
        return booking_payload(repo.bookings(conn, user_id, booking_id)[0])


def cancel_booking(conn, user_id, booking_id):
    with conn.transaction():
        run = repo.booking_run(conn, user_id, booking_id)
        if run is None:
            raise not_found("No booking matches this user and booking ID.")
        # Cancellation and allocation use the same lock and lock order.
        repo.find_run(conn, run["train_no"], run["service_date"], lock=True)
        if repo.mark_cancelled(conn, user_id, booking_id) is None:
            raise ApiError(409, "ALREADY_CANCELLED", "This booking is already cancelled.")
        return booking_payload(repo.bookings(conn, user_id, booking_id)[0])
