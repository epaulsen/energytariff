"""Sensor platform for grid-cap-watcher."""
from logging import getLogger
from datetime import datetime

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
    UnitOfEnergy,
    UnitOfPower,
)

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_point_in_time,
)
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
    MAX_EFFECT_ALLOWED,
    ROUNDING_PRECISION,
    TARGET_ENERGY,
)

from .coordinator import GridCapacityCoordinator, EnergyData, GridThresholdData

from .utils import (
    start_of_next_hour,
    seconds_between,
    convert_to_watt,
    get_rounding_precision,
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
        vol.Optional(TARGET_ENERGY): cv.positive_float,
        vol.Optional(MAX_EFFECT_ALLOWED): cv.positive_float,
        vol.Optional(ROUNDING_PRECISION): cv.positive_int,
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

    rx_coord = GridCapacityCoordinator(hass)
    async_add_entities(
        [
            GridCapWatcherEnergySensor(hass, config, rx_coord),
            GridCapWatcherEstimatedEnergySensor(hass, config, rx_coord),
            GridCapWatcherAverageThreePeakHours(hass, config, rx_coord),
            GridCapWatcherAvailableEffectRemainingHour(hass, config, rx_coord),
        ]
    )
    if config.get(GRID_LEVELS) is not None:
        async_add_entities(
            [
                GridCapWatcherCurrentEffectLevelThreshold(hass, config, rx_coord),
                GridCapacityWatcherCurrentLevelName(hass, config, rx_coord),
                GridCapacityWatcherCurrentLevelPrice(hass, config, rx_coord),
            ]
        )


class GridCapWatcherEnergySensor(RestoreSensor):
    """grid_cap_watcher Energy sensor class."""

    _state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._precision = get_rounding_precision(config)
        self._last_update = None
        self.attr = {
            CONF_EFFECT_ENTITY: self._effect_sensor_id,
            PEAK_HOUR: None,
        }
        self._last_reading = None
        self._coordinator = rx_coord
        self._attr_icon: str = ICON
        self._energy_consumed = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_kWh".replace("sensor.", "")
        )

        self.__unsub = async_track_state_change(
            hass, self._effect_sensor_id, self.__handle_event
        )
        async_track_point_in_time(
            hass, self.__handle_reset, start_of_next_hour(dt.now())
        )


    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_sensor_data()
        if savedstate and savedstate.native_value is not None:
            self._energy_consumed = float(savedstate.native_value)

    async def async_will_remove_from_hass(self) -> None:
        self.__unsub()

    async def __handle_reset(self, time):
        _LOGGER.debug('Hourly reset')
        self._energy_consumed = 0
        await self.fire_event(self._last_reading, time)
        self.async_schedule_update_ha_state(True)
        async_track_point_in_time(self._hass, self.__handle_reset, start_of_next_hour(time))

    async def __handle_event(self, entity, old_state, new_state):

        if new_state is None or old_state is None:
            return
        if new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        self._last_reading = convert_to_watt(new_state)

        diff = seconds_between(new_state.last_updated, old_state.last_updated)
        watt = convert_to_watt(old_state)
        self._energy_consumed += round(
             (diff * watt) / (3600 * 1000),
             self._precision)
        await self.fire_event(watt, old_state.last_updated)
        self.async_schedule_update_ha_state(True)

    async def fire_event(self, power: float, timestamp: datetime) -> bool:
        """Fire HA event so that dependent sensors can update their respective values"""

        self._coordinator.effectstate.on_next(
            EnergyData(self._energy_consumed, power, timestamp)
        )
        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Energy used this hour"

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
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._coordinator = rx_coord
        self._precision = get_rounding_precision(config)
        self._current_effect = None
        self._consumption = None
        self._sensor_value = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_estimate_kWh".replace(
                "sensor.", ""
            )
        )

        self._coordinator.effectstate.subscribe(lambda state: self._state_change(state))

    def _state_change(self, state: EnergyData):
        if state is None:
            return
        self._consumption = state.energy_consumed
        self._current_effect = state.current_effect
        update_time = state.timestamp

        remaining_seconds = seconds_between(
            start_of_next_hour(update_time), update_time
        )

        if remaining_seconds == 0:
            # Avoid division by zero
            remaining_seconds = 1

        self._sensor_value = round(
            self._consumption + self._current_effect * remaining_seconds / 3600 / 1000,
            self._precision,
        )
        self.schedule_update_ha_state()

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
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._coordinator = rx_coord
        self._sensor_value = None
        self._last_update = dt.now()
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_effect_threshold_kwh".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": [], "level_name": "Unknown", "price": "Unknown"}

        self._levels = config.get(GRID_LEVELS)

        self._coordinator.effectstate.subscribe(lambda state: self._state_change(state))

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

    def _state_change(self, state: EnergyData):

        if state is None:
            return
        day = state.timestamp.day
        hour = state.timestamp.hour
        energy = state.energy_consumed
        timestamp = state.timestamp

        if self._last_update is not None and timestamp.month != self._last_update.month:

            _LOGGER.debug("New month: %s", timestamp)
            # New month, so reset top_three list and sensor value
            self.attr["top_three"].clear()
            self._sensor_value = None

        self._last_update = timestamp

        consumption = {
            "day": day,
            "hour": hour,
            "energy": energy,
        }

        # Case 1:Empty list. Uncricitally add, calculate level and return
        if len(self.attr["top_three"]) == 0:
            self.attr["top_three"].append(consumption)
            self.calculate_level()
            return

        # Case 2: Same day.  If higher energy usage,  update entry, calculate and return
        for i in range(len(self.attr["top_three"])):
            if self.attr["top_three"][i]["day"] == consumption["day"]:
                if self.attr["top_three"][i]["energy"] < consumption["energy"]:
                    self.attr["top_three"][i] = consumption
                    self.calculate_level()
                return

        # Case 3: We are not on the same day, but have less than 3 items in list.
        # Add, re-calculate and return
        if len(self.attr["top_three"]) < 3:
            self.attr["top_three"].append(consumption)
            self.calculate_level()
            return

        # Case 4: Not same day, list has three element.
        # If lowest level has lower consumption, replace element,
        # recalculate and return
        self.attr["top_three"].sort(key=lambda x: x["energy"])
        for i in range(len(self.attr["top_three"])):
            if self.attr["top_three"][i]["energy"] < consumption["energy"]:
                self.attr["top_three"][i] = consumption
                self.calculate_level()
                return

    def calculate_level(self) -> bool:
        """Calculate the grid threshold level based on average of the highest hours"""

        average_value = 0.0
        for hour in self.attr["top_three"]:
            average_value += hour["energy"]

        average_value = round(average_value / len(self.attr["top_three"]), 2)

        found_threshold = self.get_level(average_value)

        if found_threshold is not None:

            if (
                self._sensor_value is None
                or self._sensor_value - found_threshold["threshold"] != 0
            ):
                self._sensor_value = found_threshold["threshold"]
                self.schedule_update_ha_state()

            # Notify other sensors that threshold level has been updated
            self._coordinator.thresholddata.on_next(
                GridThresholdData(
                    found_threshold["name"],
                    float(found_threshold["threshold"]),
                    float(found_threshold["price"]),
                    self.attr["top_three"],
                )
            )
        return True

    def get_level(self, average: float) -> Any:
        """Gets the current threshold level"""

        for level in self._levels:
            if average - level["threshold"] < 0:
                return level

        _LOGGER.error(
            "Hourly energy is outside capacity level steps.  Check configuration!"
        )
        return None

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Energy level upper threshold"

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
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._coordinator = rx_coord
        self._precision = get_rounding_precision(config)
        self._sensor_value = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_three_peak_hours_average".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": []}

        self._levels = config.get(GRID_LEVELS)

        self._coordinator.thresholddata.subscribe(
            lambda state: self._state_change(state)
        )

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

    def _state_change(self, state: GridThresholdData):
        if state is None:
            return
        self.attr["top_three"] = state.top_three
        self.calculate_sensor()

    def calculate_sensor(self) -> bool:
        """Calculate the grid threshold level based on average of the highest hours"""
        average_value = 0.0
        for hour in self.attr["top_three"]:
            average_value += hour["energy"]

        average_value = round(
            average_value / len(self.attr["top_three"]), self._precision
        )

        self._sensor_value = round(average_value, self._precision)
        self.schedule_update_ha_state(True)
        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Average peak hour energy"

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


class GridCapWatcherAvailableEffectRemainingHour(RestoreSensor, RestoreEntity):
    """Sensor that measures the max power draw that can be consumed
    for the remainin part of current hour"""

    _state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):

        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._effect = None
        self._energy = None
        self._coordinator = rx_coord
        self._precision = get_rounding_precision(config)
        self._max_effect = config.get(MAX_EFFECT_ALLOWED)
        self._target_energy = config.get(TARGET_ENERGY)
        self._sensor_value = None
        self.attr = {"grid_threshold_level": self._target_energy}

        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_remaining_effect_available".replace(
                "sensor.", ""
            )
        )
        if self._target_energy is None:
            self._coordinator.thresholddata.subscribe(
                lambda state: self._threshold_state_change(state)
            )

        self._coordinator.effectstate.subscribe(
            lambda state: self._effect_state_change(state)
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._sensor_value = float(savedstate.state)
            if "grid_threshold_level" in savedstate.attributes:
                self.attr["grid_threshold_level"] = savedstate.attributes[
                    "grid_threshold_level"
                ]

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self.attr["grid_threshold_level"] = state.level
        self.__calculate()

    def _effect_state_change(self, state: EnergyData):
        if state is None:
            return
        self._energy = state.energy_consumed
        self._effect = state.current_effect
        self.__calculate()

    def __calculate(self):
        if (
            self._energy is None
            or self._effect is None
            or self.attr["grid_threshold_level"] is None
        ):
            return

        remaining_kwh = self.attr["grid_threshold_level"] - self._energy

        seconds_remaing = seconds_between(start_of_next_hour(dt.now()), dt.now())

        if seconds_remaing < 1:
            seconds_remaing = 1

        watt_seconds = remaining_kwh * 3600 * 1000

        effect = round(watt_seconds / seconds_remaing - self._effect, self._precision)

        if self._max_effect is not None and float(self._max_effect) < effect:
            # Max effect threshold exceeded,
            # we should display max_effect - current_effect from meter
            effect = float(self._max_effect) - self._effect

        self._sensor_value = effect
        self.schedule_update_ha_state(True)

        return True

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Available power this hour"

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


class GridCapacityWatcherCurrentLevelName(RestoreSensor):
    """Sensor that measures the max power draw that can be consumed for
    the remainin part of current hour"""

    _state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._coordinator = rx_coord
        self._hass = hass
        self._sensor_value = None
        self._levels = config.get(GRID_LEVELS)
        self._attr_unique_id = f"{DOMAIN}_effect_level_name".replace("sensor.", "")
        self._coordinator.thresholddata.subscribe(
            lambda state: self._threshold_state_change(state)
        )

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self._sensor_value = state.name
        self.schedule_update_ha_state(True)

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
        return "Energy level name"

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
        return "mdi:rename-box"


class GridCapacityWatcherCurrentLevelPrice(RestoreSensor):
    """Sensor that measures the max power draw that can be consumed for
    the remainin part of current hour"""

    _state_class = SensorStateClass.MEASUREMENT

    # TODO: How to globalize this??
    _attr_native_unit_of_measurement = "NOK"

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._coordinator = rx_coord
        self._hass = hass
        self._sensor_value = None
        self._levels = config.get(GRID_LEVELS)
        self._attr_unique_id = f"{DOMAIN}_effect_level_price".replace("sensor.", "")
        self._coordinator.thresholddata.subscribe(
            lambda state: self._threshold_state_change(state)
        )

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self._sensor_value = state.price
        self.schedule_update_ha_state(True)

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
        return "Energy level price"

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
        return "mdi:cash"
