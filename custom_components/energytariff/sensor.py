"""Sensor platform for grid-cap-watcher."""

from logging import getLogger
from datetime import datetime
from typing import Any
import voluptuous as vol
from homeassistant.util import dt
import homeassistant.helpers.config_validation as cv
from homeassistant.core import Event, EventStateChangedData, callback

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
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
)

from .const import (
    DOMAIN,
    ICON,
    CONF_EFFECT_ENTITY,
    LEVEL_NAME,
    LEVEL_THRESHOLD,
    LEVEL_PRICE,
    GRID_LEVELS,
    MAX_EFFECT_ALLOWED,
    ROUNDING_PRECISION,
    TARGET_ENERGY,
    RESET_TOP_THREE,
)

from .coordinator import GridCapacityCoordinator, EnergyData, GridThresholdData

from .utils import (
    start_of_next_hour,
    start_of_next_month,
    seconds_between,
    convert_to_watt,
    get_rounding_precision,
    calculate_top_three,
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


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
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
        self._coordinator = rx_coord
        self._attr_icon: str = ICON
        self._state = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_kWh".replace("sensor.", "")
        )

        # Listen to input sensor state change event
        self.__unsub = async_track_state_change_event(
            hass, self._effect_sensor_id, self._async_on_change
        )

        # Setup hourly sensor reset.
        async_track_point_in_time(hass, self.hourly_reset, start_of_next_hour(dt.now()))

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_sensor_data()
        if savedstate and savedstate.native_value is not None:
            self._state = float(savedstate.native_value)

    async def async_will_remove_from_hass(self) -> None:
        self.__unsub()

    @callback
    def hourly_reset(self, time):
        """Callback that HA invokes at the start of each hour to reset this sensor value"""

        _LOGGER.debug("Hourly reset")
        self._state = 0
        self.async_schedule_update_ha_state(True)
        #self.fire_event(0, time)   <-- Commented as this somehow causes problems for some installations.
        async_track_point_in_time(
            self._hass, self.hourly_reset, start_of_next_hour(time)
        )

    @callback
    def _async_on_change(self, event: Event[EventStateChangedData]) -> None:
        """Callback for when the AMS sensor changes"""

        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        if new_state is None or old_state is None:
            return
        if new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        if self._state is None:
            self._state = 0

        diff = seconds_between(new_state.last_updated, old_state.last_updated)
        watt = convert_to_watt(old_state)
        if diff > 3600:
            _LOGGER.warning("More than 1 hour since last update, discarding result")
            return

        self._state += (diff * watt) / (3600 * 1000)
        self.fire_event(watt, old_state.last_updated)
        self.async_schedule_update_ha_state(True)

    def fire_event(self, power: float, timestamp: datetime) -> bool:
        """Fire HA event so that dependent sensors can update their respective values"""

        self._coordinator.effectstate.on_next(EnergyData(self._state, power, timestamp))
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
        if not self._state is None:
            return round(self._state, self._precision)
        return self._state

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON


class GridCapWatcherEstimatedEnergySensor(SensorEntity):
    """Estimated consumption per hour"""

    _state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._coordinator = rx_coord
        self._precision = get_rounding_precision(config)
        self._state = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_estimate_kWh".replace(
                "sensor.", ""
            )
        )

        self._coordinator.effectstate.subscribe(self._state_change)

    def _state_change(self, state: EnergyData):
        if state is None:
            return

        if state.energy_consumed is None or state.current_effect is None:
            return

        energy = state.energy_consumed
        power = state.current_effect
        update_time = state.timestamp

        remaining_seconds = seconds_between(
            start_of_next_hour(update_time), update_time
        )

        if remaining_seconds == 0:
            # Avoid division by zero
            remaining_seconds = 1

        self._state = energy + power * remaining_seconds / 3600 / 1000
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
        if self._state is not None:
            return round(self._state, self._precision)
        return self._state

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
        self._state = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_effect_threshold_kwh".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": []}

        self._levels = config.get(GRID_LEVELS)

        self._coordinator.effectstate.subscribe(self._state_change)

        hass.bus.async_listen(RESET_TOP_THREE, self.handle_reset_event)

        async_track_point_in_time(
            hass, self._async_reset_meter, start_of_next_month(dt.as_local(dt.now()))
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = float(savedstate.state)
            if "top_three" in savedstate.attributes:
                for item in savedstate.attributes["top_three"]:
                    self.attr["top_three"].append(
                        {
                            "day": item["day"],
                            "hour": item["hour"],
                            "energy": item["energy"],
                        }
                    )

    @callback
    def _async_reset_meter(self, _):
        """Resets the attributes so that we don't carry over old values to new month"""
        self.attr["top_three"] = []
        self.schedule_update_ha_state(True)
        _LOGGER.debug("Monthly reset")
        async_track_point_in_time(
            self._hass,
            self._async_reset_meter,
            start_of_next_month(dt.as_local(dt.now())),
        )

    @callback
    def handle_reset_event(self, event):
        """Handle reset event to reset top three attributes"""
        self._async_reset_meter(event)

    def _state_change(self, state: EnergyData) -> None:
        if state is None:
            return

        self.attr["month"] = dt.as_local(dt.now()).month
        self.attr["top_three"] = calculate_top_three(state, self.attr["top_three"])
        self.calculate_level()

    def calculate_level(self) -> bool:
        """Calculate the grid threshold level based on average of the highest hours"""

        average_value = 0.0
        for hour in self.attr["top_three"]:
            average_value += hour["energy"]

        average_value = average_value / len(self.attr["top_three"])

        found_threshold = self.get_level(average_value)

        if found_threshold is not None:
            self._state = found_threshold["threshold"]
            self.schedule_update_ha_state(True)

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

        _LOGGER.warning(
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
        return self._state is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._state

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
        self._state = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_grid_three_peak_hours_average".replace(
                "sensor.", ""
            )
        )

        self.attr = {"top_three": []}

        self._levels = config.get(GRID_LEVELS)

        self._coordinator.effectstate.subscribe(self._state_change)

        hass.bus.async_listen(RESET_TOP_THREE, self.handle_reset_event)

        async_track_point_in_time(
            hass, self._async_reset_meter, start_of_next_month(dt.as_local(dt.now()))
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = float(savedstate.state)
            if "top_three" in savedstate.attributes:
                for item in savedstate.attributes["top_three"]:
                    self.attr["top_three"].append(
                        {
                            "day": item["day"],
                            "hour": item["hour"],
                            "energy": item["energy"],
                        }
                    )

    @callback
    def _async_reset_meter(self, _):
        """Resets the attributes so that we don't carry over old values to new month"""
        self.attr["top_three"] = []
        self.schedule_update_ha_state(True)
        _LOGGER.debug("Monthly reset")
        async_track_point_in_time(
            self._hass,
            self._async_reset_meter,
            start_of_next_month(dt.as_local(dt.now())),
        )

    @callback
    def handle_reset_event(self, event):
        """Handle reset event to reset top three attributes"""
        self._async_reset_meter(event)

    def _state_change(self, state: EnergyData) -> None:
        if state is None:
            return

        self.attr["top_three"] = calculate_top_three(state, self.attr["top_three"])

        totalSum = float(0)
        for hour in self.attr["top_three"]:
            totalSum += float(hour["energy"])

        if len(self.attr["top_three"]) == 0:
            return

        self._state = totalSum / len(self.attr["top_three"])
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
        return self._state is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        if self._state is not None:
            return round(self._state, self._precision)
        return self._state

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
        self._state = None
        self.attr = {"grid_threshold_level": self._target_energy}

        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_remaining_effect_available".replace(
                "sensor.", ""
            )
        )

        self._coordinator.thresholddata.subscribe(self._threshold_state_change)
        self._coordinator.effectstate.subscribe(self._effect_state_change)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = float(savedstate.state)
            if "grid_threshold_level" in savedstate.attributes:
                self.attr["grid_threshold_level"] = savedstate.attributes[
                    "grid_threshold_level"
                ]
            self.__calculate()

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self.attr["grid_threshold_level"] = state.level
        self.__calculate()
        self.schedule_update_ha_state(True)

    def _effect_state_change(self, state: EnergyData):
        if state is None:
            return
        self._energy = state.energy_consumed
        self._effect = state.current_effect
        self.__calculate()
        self.schedule_update_ha_state(True)

    def __calculate(self):
        if (
            self._energy is None
            or self._effect is None
            or (
                self.attr["grid_threshold_level"] is None
                and self._target_energy is None
            )
        ):
            return

        if self._target_energy is None:
            threshold_energy = float(self.attr["grid_threshold_level"])
        else:
            threshold_energy = float(self._target_energy)

        remaining_kwh = threshold_energy - self._energy

        seconds_remaing = seconds_between(start_of_next_hour(dt.now()), dt.now())

        if seconds_remaing < 1:
            seconds_remaing = 1

        watt_seconds = remaining_kwh * 3600 * 1000

        power = watt_seconds / seconds_remaing - self._effect

        if self._max_effect is not None and float(self._max_effect) < power:
            # Max effect threshold exceeded,
            # we should display max_effect - current_effect from meter
            power = float(self._max_effect) - self._effect

        if (
            self._max_effect is not None
            and power < 0
            and float(self._max_effect) * -1 > power
        ):
            # Do not exceed threshold in negative direction either.
            # Purely cosmetic, but it messes up scale on graph.
            power = float(self._max_effect) * -1

        self._state = power

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
        return self._state is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        if self._state is not None:
            return round(self._state, self._precision)
        return self._state

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
        self._state = None
        self._levels = config.get(GRID_LEVELS)
        self._attr_unique_id = f"{DOMAIN}_effect_level_name".replace("sensor.", "")
        self._coordinator.thresholddata.subscribe(self._threshold_state_change)

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self._state = state.name
        self.schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = savedstate.state

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
        return self._state is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._state

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
        self._state = None
        self._levels = config.get(GRID_LEVELS)
        self._attr_unique_id = f"{DOMAIN}_effect_level_price".replace("sensor.", "")
        self._coordinator.thresholddata.subscribe(self._threshold_state_change)

    def _threshold_state_change(self, state: GridThresholdData):
        if state is None:
            return
        self._state = state.price
        self.schedule_update_ha_state(True)

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = savedstate.state

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
        return self._state is not None

    @property
    def native_value(self):
        """Returns the native value for this sensor"""
        return self._state

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return "mdi:cash"
