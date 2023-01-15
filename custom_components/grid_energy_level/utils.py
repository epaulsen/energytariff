from datetime import datetime, timedelta
from typing import Any
from .const import ROUNDING_PRECISION

# from typing import Any, Callable, Optional
# import voluptuous as vol
# from homeassistant.util import dt


def start_of_current_hour(date_object: datetime) -> datetime:
    """Returns a datetime object which is set to start of input objects current time"""
    return datetime(
        date_object.year,
        date_object.month,
        date_object.day,
        date_object.hour,
        0,
        0,
        tzinfo=date_object.tzinfo,
    )


def start_of_next_hour(date_object: datetime) -> datetime:
    """returns a datetime object that is the start of next hour"""
    temp = date_object + timedelta(hours=1)
    value = datetime(
        temp.year,
        temp.month,
        temp.day,
        temp.hour,
        0,
        0,
        tzinfo=temp.tzinfo,
    )
    return value


def seconds_between(date_object_1: datetime, date_object_2: datetime) -> int:
    """Returns number of seconds between two dates"""
    return (date_object_1 - date_object_2).total_seconds()


def get_rounding_precision(config: dict[str, Any]) -> float:
    """Gets rounding precision for sensors with decimal value.
    Default to the value 2 for 2 decimals"""
    precision = config.get(ROUNDING_PRECISION)
    if precision is None:
        return 2

    return float(precision)


def convert_to_watt(data: any) -> float:
    """Converts input sensor data to watt, if needed"""
    value = float(data.state)
    unit = data.attributes["unit_of_measurement"]
    if unit == "kW":
        value = value * 1000
    else:
        if unit != "W":
            return None
    return value
