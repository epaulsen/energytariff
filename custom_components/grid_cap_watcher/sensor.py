"""Sensor platform for grid-cap-watcher."""
from logging import getLogger
from datetime import datetime, timedelta

from typing import Any, Callable, Optional
import voluptuous as vol
from homeassistant.util import dt
import homeassistant.helpers.config_validation as cv

from homeassistant.components.sensor import (
    SensorStateClass,
    RestoreSensor,
    SensorEntity,
    RestoreEntity,
    PLATFORM_SCHEMA,
)

from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

from homeassistant.core import callback
from homeassistant.helpers.typing import (
    ConfigType,
    DiscoveryInfoType,
    HomeAssistantType,
)

from .const import (
    DOMAIN,
    ICON,
    CONF_EFFECT_ENTITY,
    LEVEL_NAME,
    LEVEL_THRESHOLD,
    LEVEL_PRICE,
    GRID_LEVELS,
    PEAK_HOUR,
    SENSOR_DATA_UPDATED,
    SENSOR_DATA_EFFECT_LEVEL_CHANGED,
    SENSOR_DATA_TOP_THREE_CHANGED,
)

from .utils import (
    start_of_next_hour,
    seconds_between,
    start_of_current_hour,
    convert_to_watt,
)

_LOGGER = getLogger(__name__)

LEVEL_SCHEMA = vol.Schema(
    {
        vol.Required(LEVEL_NAME): cv.string,
        vol.Required(LEVEL_THRESHOLD): cv.Number,
        vol.Required(LEVEL_PRICE): cv.Number,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_EFFECT_ENTITY): cv.string,
        vol.Optional(GRID_LEVELS): vol.All(cv.ensure_list, [LEVEL_SCHEMA]),
    }
)


async def async_setup_platform(
    hass: HomeAssistantType,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Setup sensor platform."""
    async_add_entities(
        [
            GridCapWatcherEnergySensor(hass, config),
            GridCapWatcherEstimatedEnergySensor(hass, config),
            GridCapWatcherCurrentEffectLevelThreshold(hass, config),
            GridCapWatcherAverageThreePeakHours(hass, config),
            GridCapWatcherAvailableEffectRemainingHour(hass, config),
            GridCapacityWatcherCurrentLevelName(hass, config),
        ]
    )


class GridCapWatcherEnergySensor(RestoreSensor):
    """grid_cap_watcher Sensor class."""

    _state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass, config):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self.attr = {
            CONF_EFFECT_ENTITY: self._effect_sensor_id,
            PEAK_HOUR: None,
        }
        self._attr_icon: str = ICON
        self._energy_consumed = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_kWh".replace("sensor.", "")
        )

        hass.bus.async_listen(EVENT_STATE_CHANGED, self.__handle_event)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_sensor_data()
        if savedstate and savedstate.native_value is not None:
            self._energy_consumed = float(savedstate.native_value)

    async def __handle_event(self, event):
        if event.data["entity_id"] == self._effect_sensor_id:

            new_updated = event.data["new_state"].last_updated
            new_value = convert_to_watt(event.data["new_state"])

            if event.data["old_state"] is not None:
                old_value = convert_to_watt(event.data["old_state"])
                old_updated = event.data["old_state"].last_updated

                if (
                    self._energy_consumed not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
                    and self._energy_consumed is not None
                ):
                    current_state = self._energy_consumed
                else:
                    current_state = 0

                # Crossing hour threshold.  Reset energy counter
                if old_updated.hour != new_updated.hour:
                    cutoff = start_of_current_hour(new_updated)

                    # Calculate energy for last update on old hour first
                    diff = (cutoff - old_updated).total_seconds()
                    if diff > 0:
                        watt_seconds = old_value * diff
                        self._energy_consumed = round(
                            current_state + watt_seconds / 3600 / 1000, 2
                        )  # Output is kWh

                    # Fire HA event so that sensor which holds current capacity level info can update
                    await self.fire_event(new_value, old_updated)

                    # Set diff so that we calculate from first second of hour for remaining value
                    diff = (new_updated - cutoff).total_seconds()

                    # Set energy to zero, as we are starting a new hour
                    current_state = 0
                else:
                    diff = seconds_between(new_updated, old_updated)

                # Calculate watt-seconds
                if diff > 0:
                    watt_seconds = old_value * diff
                    self._energy_consumed = round(
                        current_state + watt_seconds / 3600 / 1000, 2
                    )  # Output is kWh
                    self.async_schedule_update_ha_state(True)

                    # Fire HA event so that other sensors can be updated
                    await self.fire_event(new_value, new_updated)

    async def fire_event(self, effect: float, timestamp: datetime) -> bool:
        """Fire HA event so that dependent sensors can update their respective values"""
        event_data = {
            "consumption": self._energy_consumed,
            "effect": effect,
            "timestamp": timestamp,
        }
        self._hass.bus.async_fire(SENSOR_DATA_UPDATED, event_data)
        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Energy used"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def native_value(self):
        return self._energy_consumed

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON

    @property
    def extra_state_attributes(self):
        return self.attr


class GridCapWatcherEstimatedEnergySensor(SensorEntity):
    """Estimated consumption per hour"""

    _state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass, config):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._current_effect = None
        self._consumption = None
        self._sensor_value = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_estimate_kWh".replace(
                "sensor.", ""
            )
        )

        hass.bus.async_listen(SENSOR_DATA_UPDATED, self.__handle_event)

    async def __handle_event(self, event):

        self._consumption = float(event.data["consumption"])
        self._current_effect = float(event.data["effect"])
        update_time = event.data["timestamp"]

        remaining_seconds = seconds_between(
            start_of_next_hour(update_time), update_time
        )

        if remaining_seconds == 0:
            # Avoid division by zero
            remaining_seconds = 1

        self._sensor_value = round(
            self._consumption + self._current_effect * remaining_seconds / 3600 / 1000,
            2,
        )
        self.async_schedule_update_ha_state(True)

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Energy estimate this hour"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._sensor_value

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON


class GridCapWatcherCurrentEffectLevelThreshold(RestoreSensor, RestoreEntity):
    """Sensor that holds the grid effect level we are at"""

    _state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass, config):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._current_effect = None
        self._consumption = None
        self._sensor_value = None
        self._last_update = dt.now()
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_effect_threshold_kwh".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": [], "level_name": "Unknown", "price": "Unknown"}

        self._levels = config.get(GRID_LEVELS)

        hass.bus.async_listen(SENSOR_DATA_UPDATED, self.__handle_event)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._sensor_value = float(savedstate.state)
            if "top_three" in savedstate.attributes:
                for item in savedstate.attributes["top_three"]:
                    self.attr["top_three"].append(
                        {
                            "day": item["day"],
                            "hour": item["hour"],
                            "energy": item["energy"],
                        }
                    )

    async def __handle_event(self, event):

        if dt.now().month != self._last_update.month:
            # New month, so reset top_three list and sensor value
            self.attr["top_three"].clear()
            self._sensor_value = None

        # day = int(event.data["day"])
        # hour = int(event.data["hour"])
        day = event.data["timestamp"].day
        hour = event.data["timestamp"].hour
        energy = float(event.data["consumption"])
        self._last_update = dt.now()

        consumption = {
            "day": day,
            "hour": hour,
            "energy": energy,
        }

        # Case 1:Empty list. Uncricitally add, calculate level and return
        if len(self.attr["top_three"]) == 0:
            self.attr["top_three"].append(consumption)
            await self.calculate_level()
            return

        # Case 2: Same day.  If higher energy usage,  update entry, calculate and return
        for i in range(len(self.attr["top_three"])):
            if self.attr["top_three"][i]["day"] == consumption["day"]:
                if self.attr["top_three"][i]["energy"] < consumption["energy"]:
                    self.attr["top_three"][i] = consumption
                    await self.calculate_level()
                return

        # Case 3: We are not on the same day, but have less than 3 items in list.  Add, re-calculate and return
        if len(self.attr["top_three"]) < 3:
            self.attr["top_three"].append(consumption)
            await self.calculate_level()
            return

        # Case 4: Not same day, list has three element.  If lowest level has lower consumption, replace element, recalculate and return
        self.attr["top_three"].sort(key=lambda x: x.energy)
        for i in range(len(self.attr["top_three"])):
            if self.attr["top_three"][i]["energy"] < consumption["energy"]:
                self.attr["top_three"][i] = consumption
                await self.calculate_level()
                return

    async def calculate_level(self) -> bool:
        """Calculate the grid threshold level based on average of the highest hours"""

        # If we got this far, fire event to notify average sensor that top three
        # hours has changed.  Fire event containing top_three attributes
        self._hass.bus.async_fire(
            SENSOR_DATA_TOP_THREE_CHANGED, {"top_three": self.attr["top_three"]}
        )

        average_value = 0.0
        for hour in self.attr["top_three"]:
            average_value += hour["energy"]

        average_value = round(average_value / len(self.attr["top_three"]), 2)

        found_threshold = self.get_level(average_value)

        if found_threshold is not None and (
            self._sensor_value is None
            or self._sensor_value - found_threshold["threshold"] != 0
        ):
            self._sensor_value = found_threshold["threshold"]

            self.async_schedule_update_ha_state(True)
            event_data = {
                "level": found_threshold,
            }
            self._hass.bus.async_fire(SENSOR_DATA_EFFECT_LEVEL_CHANGED, event_data)
        return True

    def get_level(self, average: float) -> Any:
        """Gets the current threshold level"""

        for i in range(len(self._levels)):
            if average - self._levels[i]["threshold"] < 0:
                return self._levels[i]

        _LOGGER.error(
            "Hourly energy is outside capacity level steps.  Check configuration!"
        )
        return None

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Grid effect level"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._sensor_value is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._sensor_value

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON

    @property
    def extra_state_attributes(self):
        return self.attr


class GridCapWatcherAverageThreePeakHours(RestoreSensor, RestoreEntity):
    """Sensor that holds the average value of the three peak hours this month"""

    _state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass, config):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._current_effect = None
        self._consumption = None
        self._sensor_value = None
        self._last_update = dt.now()
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_three_peak_hours_average".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": []}

        self._levels = config.get(GRID_LEVELS)
        hass.bus.async_listen(SENSOR_DATA_TOP_THREE_CHANGED, self.__top_three_changed)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._sensor_value = float(savedstate.state)
            if "top_three" in savedstate.attributes:
                for item in savedstate.attributes["top_three"]:
                    self.attr["top_three"].append(
                        {
                            "day": item["day"],
                            "hour": item["hour"],
                            "energy": item["energy"],
                        }
                    )

    async def __top_three_changed(self, event):
        self.attr["top_three"] = event.data["top_three"]
        await self.calculate_sensor()

    async def calculate_sensor(self) -> bool:
        """Calculate the grid threshold level based on average of the highest hours"""
        average_value = 0.0
        for hour in self.attr["top_three"]:
            average_value += hour["energy"]

        average_value = round(average_value / len(self.attr["top_three"]), 2)

        self._sensor_value = round(average_value, 2)
        self.async_schedule_update_ha_state(True)
        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Average peak hour effect"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._sensor_value is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._sensor_value

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON

    @property
    def extra_state_attributes(self):
        return self.attr


class GridCapWatcherAvailableEffectRemainingHour(SensorEntity):
    """Sensor that measures the max power draw that can be consumed for the remainin part of current hour"""

    _state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"

    def __init__(self, hass, config):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._current_effect = None
        self._consumption = None
        self._sensor_value = None
        self._last_update = dt.now()
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_remaining_effect_available".replace(
                "sensor.", ""
            )
        )
        hass.bus.async_listen(SENSOR_DATA_UPDATED, self.__handle_effect_level_event)

    # async def __handle_effect_level_event(self, event):

    async def __handle_effect_level_event(self, event):
        self._consumption = float(event.data["consumption"])
        effect = float(event.data["effect"])
        threshold_state = self._hass.states.get("sensor.grid_effect_level")
        if threshold_state is not None and threshold_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            remaining_kWh = float(threshold_state.state) - self._consumption

            seconds_remaing = seconds_between(start_of_next_hour(dt.now()), dt.now())

            if seconds_remaing < 1:
                seconds_remaing = 1

            watt_seconds = remaining_kWh * 3600 * 1000

            self._sensor_value = round(watt_seconds / seconds_remaing - effect, 2)
            self.async_schedule_update_ha_state(True)

        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Available effect"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._sensor_value is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._sensor_value

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON


class GridCapacityWatcherCurrentLevelName(RestoreSensor):
    """Sensor that measures the max power draw that can be consumed for
    the remainin part of current hour"""

    _state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, config):
        self._hass = hass
        self._sensor_value = None
        self._levels = config.get(GRID_LEVELS)
        self._attr_unique_id = f"{DOMAIN}_effect_level_name".replace("sensor.", "")
        hass.bus.async_listen(SENSOR_DATA_UPDATED, self.__handle_event)

    async def __handle_event(self, event):

        self._sensor_value = event.data["level"]["name"]
        self.async_schedule_update_ha_state(True)

        return True

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._sensor_value = savedstate.state

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Grid effect level name"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._sensor_value is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._sensor_value

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON
