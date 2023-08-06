from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

from custom_components.energytariff.coordinator import EnergyData

from .const import ROUNDING_PRECISION


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


def start_of_next_month(date_object: datetime) -> datetime:
    """Returns a datetime object that is set at start of next month + 1 second."""
    if date_object.month == 12:
        month = 1
        year = date_object.year + 1
    else:
        month = date_object.month + 1
        year = date_object.year

    value = datetime(year, month, 1, 0, 0, 1, 0, tzinfo=date_object.tzinfo)
    return value


def seconds_between(date_object_1: datetime, date_object_2: datetime) -> int:
    """Returns number of seconds between two dates"""
    return (date_object_1 - date_object_2).total_seconds()


def get_rounding_precision(config: dict[str, Any]) -> int:
    """Gets rounding precision for sensors with decimal value.
    Default to the value 2 for 2 decimals"""
    precision = config.get(ROUNDING_PRECISION)
    if precision is None:
        return 2

    return int(precision)


def convert_to_watt(data: any) -> float:
    """Converts input sensor data to watt, if needed"""
    if data.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return 0

    value = float(data.state)
    unit = data.attributes["unit_of_measurement"]
    if unit == "kW":
        value = value * 1000
    else:
        if unit != "W":
            return None
    return value


def calculate_top_three(state: EnergyData, top_three: Any) -> Any:
    """Mainains the list of top three hours for a month"""

    if state is None:
        return top_three

    localtime = dt.as_local(state.timestamp)

    energy_used = state.energy_consumed

    # Solar or wind production can cause the energy meter to have negative values
    # Set this to 0, as tariffs are only for consumption and we don't have negative
    # tariff values in the tariff config section.
    if energy_used < 0:
        energy_used = 0

    consumption = {
        "day": localtime.day,
        "hour": localtime.hour,
        "energy": energy_used,
    }

    # Case 1:Empty list. Uncricitally add, calculate level and return
    if len(top_three) == 0:
        # _LOGGER.debug("Adding first item")
        top_three.append(consumption)
        return top_three

    # Case 2: Items in list.  If any are same day as consumption-item,
    # update that one if energy is higher.  Recalculate and return
    for i in range(len(top_three)):
        if int(top_three[i]["day"]) == int(consumption["day"]):
            if top_three[i]["energy"] < consumption["energy"]:
                top_three[i]["energy"] = consumption["energy"]
                top_three[i]["hour"] = consumption["hour"]
                # _LOGGER.debug(
                #     "Updating current-day item to %s", consumption["energy"]
                # )

            return top_three

    # Case 3: We are not on the same day as any items in the list,
    # but have less than 3 items in list.
    # Add, re-calculate and return
    if len(top_three) < 3:
        top_three.append(consumption)
        return top_three

    # Case 4: Not same day, list has three element.
    # If lowest level has lower consumption, replace element,
    # recalculate and return
    top_three.sort(key=lambda x: x["energy"])
    for i in range(len(top_three)):
        if top_three[i]["energy"] < consumption["energy"]:
            top_three[i] = consumption
            return top_three

    # If we got this far, list has no changes, to return it as-is.
    return top_three
