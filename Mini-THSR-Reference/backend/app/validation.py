from dataclasses import dataclass
from datetime import date, time
import re

from .config import END_DATE, START_DATE
from .errors import invalid

PREFERENCES = {"window": frozenset("AE"), "aisle": frozenset("CD")}


@dataclass(frozen=True)
class Trip:
    train_no: str
    service_date: date
    from_station_id: str
    to_station_id: str


def text_field(values, name):
    value = values.get(name)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise invalid(f"{name} must be a nonempty string.")
    return value


def service_date(values):
    value = text_field(values, "date")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise invalid("date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise invalid("date is not a valid calendar date.") from None
    if not START_DATE <= parsed <= END_DATE:
        raise invalid(f"date must be between {START_DATE} and {END_DATE}.")
    return parsed


def route_stations(values):
    origin = text_field(values, "from_station_id")
    destination = text_field(values, "to_station_id")
    if origin == destination:
        raise invalid("Departure and arrival stations must be different.")
    return origin, destination


def optional_time(values, name):
    if name not in values:
        return None
    value = text_field(values, name)
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise invalid(f"{name} must use HH:MM.")
    return time.fromisoformat(value)


def trip_fields(values):
    origin, destination = route_stations(values)
    return Trip(text_field(values, "train_no"), service_date(values), origin, destination)


def booking_options(values):
    count = values.get("seat_count")
    if type(count) is not int or not 1 <= count <= 5:
        raise invalid("seat_count must be an integer from 1 to 5.")
    preference = values.get("preference")
    if preference is not None:
        if count != 1 or not isinstance(preference, str) or preference not in PREFERENCES:
            raise invalid("Only a single ticket may have a window or aisle preference.")
    return count, preference
