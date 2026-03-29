"""Sensor platform for grid-cap-watcher."""

from __future__ import annotations

from datetime import datetime
from logging import getLogger
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    RestoreSensor,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.util import dt

from .const import (
    CONF_EFFECT_ENTITY,
    DOMAIN,
    GRID_LEVELS,
    ICON,
    LEVEL_NAME,
    LEVEL_PRICE,
    LEVEL_THRESHOLD,
    MAX_EFFECT_ALLOWED,
    RESET_TOP_THREE,
    ROUNDING_PRECISION,
    SECONDS_PER_HOUR,
    TARGET_ENERGY,
    WATTS_PER_KW,
)
from .coordinator import EnergyData, GridCapacityCoordinator, GridThresholdData
from .utils import (
    calculate_top_three,
    convert_to_watt,
    get_rounding_precision,
    seconds_between,
    start_of_next_hour,
    start_of_next_month,
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


def _make_device_info(effect_sensor_id: str) -> DeviceInfo:
    """Return shared DeviceInfo for all energytariff sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, effect_sensor_id)},
        name="Energy Tariff",
        manufacturer="energytariff",
    )


def _restore_top_three(savedstate: Any, attr: dict) -> None:
    """Restore top_three from saved HA state, filtering to current month only."""
    if "top_three" not in savedstate.attributes:
        return
    current_month = dt.as_local(dt.now()).month
    for item in savedstate.attributes["top_three"]:
        item_month = int(item.get("month", current_month))
        if item_month != current_month:
            continue
        attr["top_three"].append(
            {
                "month": int(item_month),
                "day": item["day"],
                "hour": item["hour"],
                "energy": item["energy"],
            }
        )


class GridCapWatcherEnergySensor(RestoreSensor):
    """grid_cap_watcher Energy sensor class."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._precision = get_rounding_precision(config)
        self._coordinator = rx_coord
        self._attr_icon: str = ICON
        self._state = None
        self._attr_unique_id = (
            f"{DOMAIN}_{self._effect_sensor_id}_consumption_kWh".replace("sensor.", "")
        )

        self._unsub_state = async_track_state_change_event(
            hass, self._effect_sensor_id, self._async_on_change
        )
        self._unsub_timer = async_track_point_in_time(
            hass, self.hourly_reset, start_of_next_hour(dt.now())
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_sensor_data()
        if savedstate and savedstate.native_value is not None:
            self._state = float(savedstate.native_value)

    async def async_will_remove_from_hass(self) -> None:
        self._unsub_state()
        if self._unsub_timer:
            self._unsub_timer()

    @callback
    def hourly_reset(self, time):
        """Callback that HA invokes at the start of each hour to reset this sensor value"""
        _LOGGER.debug("Hourly reset")
        self._state = 0
        self.async_schedule_update_ha_state(True)
        self._unsub_timer = async_track_point_in_time(
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
        if watt is None:
            return
        if diff > SECONDS_PER_HOUR:
            _LOGGER.warning("More than 1 hour since last update, discarding result")
            return

        self._state += (diff * watt) / (SECONDS_PER_HOUR * WATTS_PER_KW)
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
        if self._state is not None:
            return round(self._state, self._precision)
        return self._state

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return ICON

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapWatcherEstimatedEnergySensor(SensorEntity):
    """Estimated consumption per hour"""

    _attr_state_class = SensorStateClass.TOTAL
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

        self._disposables = [
            self._coordinator.effectstate.subscribe(self._state_change)
        ]

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()

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

        self._state = energy + power * remaining_seconds / SECONDS_PER_HOUR / WATTS_PER_KW
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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapWatcherCurrentEffectLevelThreshold(RestoreSensor):
    """Sensor that holds the grid effect level we are at"""

    _attr_state_class = SensorStateClass.MEASUREMENT
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

        self._disposables = [
            self._coordinator.effectstate.subscribe(self._state_change)
        ]
        self._unsub_bus = hass.bus.async_listen(RESET_TOP_THREE, self.handle_reset_event)
        self._unsub_timer = async_track_point_in_time(
            hass, self._async_reset_meter, start_of_next_month(dt.as_local(dt.now()))
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = float(savedstate.state)
            _restore_top_three(savedstate, self.attr)

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()
        self._unsub_bus()
        if self._unsub_timer:
            self._unsub_timer()

    @callback
    def _async_reset_meter(self, _):
        """Resets the attributes so that we don't carry over old values to new month"""
        self.attr["top_three"] = []
        self.schedule_update_ha_state(True)
        _LOGGER.debug("Monthly reset")
        self._unsub_timer = async_track_point_in_time(
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
        if not self.attr["top_three"]:
            return False

        average_value = sum(hour["energy"] for hour in self.attr["top_three"])
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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapWatcherAverageThreePeakHours(RestoreSensor):
    """Sensor that holds the average value of the three peak hours this month"""

    _attr_state_class = SensorStateClass.MEASUREMENT
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

        # Subscribe to both effectstate (for backwards compatibility and when no levels are
        # configured) and thresholddata (to get synchronized top_three from threshold sensor)
        self._disposables = [
            self._coordinator.effectstate.subscribe(self._state_change)
        ]
        if config.get(GRID_LEVELS) is not None:
            self._disposables.append(
                self._coordinator.thresholddata.subscribe(self._threshold_state_change)
            )
        self._unsub_bus = hass.bus.async_listen(RESET_TOP_THREE, self.handle_reset_event)
        self._unsub_timer = async_track_point_in_time(
            hass, self._async_reset_meter, start_of_next_month(dt.as_local(dt.now()))
        )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        savedstate = await self.async_get_last_state()
        if savedstate:
            if savedstate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._state = float(savedstate.state)
            _restore_top_three(savedstate, self.attr)

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()
        self._unsub_bus()
        if self._unsub_timer:
            self._unsub_timer()

    @callback
    def _async_reset_meter(self, _):
        """Resets the attributes so that we don't carry over old values to new month"""
        self.attr["top_three"] = []
        self.schedule_update_ha_state(True)
        _LOGGER.debug("Monthly reset")
        self._unsub_timer = async_track_point_in_time(
            self._hass,
            self._async_reset_meter,
            start_of_next_month(dt.as_local(dt.now())),
        )

    @callback
    def handle_reset_event(self, event):
        """Handle reset event to reset top three attributes"""
        self._async_reset_meter(event)

    def _threshold_state_change(self, threshold_data: GridThresholdData) -> None:
        """
        Update top_three and average from threshold sensor.

        This ensures that the average sensor and threshold sensor always use
        the same top_three data, preventing synchronization issues.
        """
        if threshold_data is None:
            return

        # Use the top_three from the threshold sensor (shallow copy to prevent reference sharing)
        self.attr["top_three"] = list(threshold_data.top_three)

        if not self.attr["top_three"]:
            return

        total_sum = sum(float(hour["energy"]) for hour in self.attr["top_three"])
        self._state = total_sum / len(self.attr["top_three"])
        self.schedule_update_ha_state(True)

    def _state_change(self, state: EnergyData) -> None:
        if state is None:
            return

        self.attr["top_three"] = calculate_top_three(state, self.attr["top_three"])

        if not self.attr["top_three"]:
            return

        total_sum = sum(float(hour["energy"]) for hour in self.attr["top_three"])
        self._state = total_sum / len(self.attr["top_three"])
        self.schedule_update_ha_state(True)

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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapWatcherAvailableEffectRemainingHour(RestoreSensor):
    """
    Sensor that measures the max power draw that can be consumed
    for the remaining part of current hour
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
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

        self._disposables = [
            self._coordinator.thresholddata.subscribe(self._threshold_state_change),
            self._coordinator.effectstate.subscribe(self._effect_state_change),
        ]

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

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()

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
            return None

        if self._target_energy is None:
            threshold_energy = float(self.attr["grid_threshold_level"])
        else:
            threshold_energy = float(self._target_energy)

        remaining_kwh = threshold_energy - self._energy

        seconds_remaining = seconds_between(start_of_next_hour(dt.now()), dt.now())
        seconds_remaining = max(seconds_remaining, 1)

        watt_seconds = remaining_kwh * SECONDS_PER_HOUR * WATTS_PER_KW

        power = watt_seconds / seconds_remaining - self._effect

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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapacityWatcherCurrentLevelName(RestoreSensor):
    """Sensor that displays the current grid capacity level name."""

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._coordinator = rx_coord
        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._state = None
        self._attr_unique_id = f"{DOMAIN}_effect_level_name".replace("sensor.", "")

        self._disposables = [
            self._coordinator.thresholddata.subscribe(self._threshold_state_change)
        ]

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

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()

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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)


class GridCapacityWatcherCurrentLevelPrice(RestoreSensor):
    """Sensor that displays the current grid capacity level price."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    # TODO: How to globalize this??
    _attr_native_unit_of_measurement = "NOK"

    def __init__(self, hass, config, rx_coord: GridCapacityCoordinator):
        self._coordinator = rx_coord
        self._hass = hass
        self._effect_sensor_id = config.get(CONF_EFFECT_ENTITY)
        self._state = None
        self._attr_unique_id = f"{DOMAIN}_effect_level_price".replace("sensor.", "")

        self._disposables = [
            self._coordinator.thresholddata.subscribe(self._threshold_state_change)
        ]

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

    async def async_will_remove_from_hass(self) -> None:
        for d in self._disposables:
            d.dispose()

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

    @property
    def device_info(self) -> DeviceInfo:
        return _make_device_info(self._effect_sensor_id)
