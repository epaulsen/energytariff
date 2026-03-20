"""Test energytariff sensor platform."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from homeassistant.util import dt
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import Event, EventStateChangedData
from custom_components.energytariff.sensor import (
    async_setup_platform,
    GridCapWatcherEnergySensor,
    GridCapWatcherEstimatedEnergySensor,
    GridCapWatcherAverageThreePeakHours,
    GridCapWatcherAvailableEffectRemainingHour,
    GridCapWatcherCurrentEffectLevelThreshold,
    GridCapacityWatcherCurrentLevelName,
    GridCapacityWatcherCurrentLevelPrice,
)
from custom_components.energytariff.coordinator import (
    GridCapacityCoordinator,
    EnergyData,
    GridThresholdData,
)
from custom_components.energytariff.const import (
    CONF_EFFECT_ENTITY,
    GRID_LEVELS,
    MAX_EFFECT_ALLOWED,
    TARGET_ENERGY,
    ROUNDING_PRECISION,
)

# Import Home Assistant test fixtures
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture
def expected_lingering_timers():
    """Allow lingering timers for sensor tests with time tracking."""
    return True


@pytest.fixture
def basic_config():
    """Create a basic sensor configuration."""
    return {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
    }


@pytest.fixture
def config_with_levels():
    """Create a sensor configuration with grid levels."""
    return {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Low", "threshold": 2.0, "price": 50},
            {"name": "Medium", "threshold": 5.0, "price": 100},
            {"name": "High", "threshold": 8.0, "price": 200},
        ],
    }


@pytest.fixture
def config_with_limits():
    """Create a sensor configuration with power limits."""
    return {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        TARGET_ENERGY: 5.0,
        MAX_EFFECT_ALLOWED: 10000.0,
        ROUNDING_PRECISION: 2,
    }


@pytest.fixture
async def mock_coordinator(hass):
    """Create a mock GridCapacityCoordinator."""
    return GridCapacityCoordinator(hass)


@pytest.mark.asyncio
async def test_async_setup_platform_basic(hass, basic_config):
    """Test sensor platform setup with basic configuration."""
    mock_add_entities = Mock()
    
    await async_setup_platform(hass, basic_config, mock_add_entities)
    
    assert mock_add_entities.called
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 4
    assert isinstance(entities[0], GridCapWatcherEnergySensor)
    assert isinstance(entities[1], GridCapWatcherEstimatedEnergySensor)
    assert isinstance(entities[2], GridCapWatcherAverageThreePeakHours)
    assert isinstance(entities[3], GridCapWatcherAvailableEffectRemainingHour)


@pytest.mark.asyncio
async def test_async_setup_platform_with_levels(hass, config_with_levels):
    """Test sensor platform setup with grid levels configuration."""
    mock_add_entities = Mock()
    
    await async_setup_platform(hass, config_with_levels, mock_add_entities)
    
    assert mock_add_entities.call_count == 2
    # First call adds 4 basic sensors
    first_call_entities = mock_add_entities.call_args_list[0][0][0]
    assert len(first_call_entities) == 4
    # Second call adds 3 level sensors
    second_call_entities = mock_add_entities.call_args_list[1][0][0]
    assert len(second_call_entities) == 3
    assert isinstance(second_call_entities[0], GridCapWatcherCurrentEffectLevelThreshold)
    assert isinstance(second_call_entities[1], GridCapacityWatcherCurrentLevelName)
    assert isinstance(second_call_entities[2], GridCapacityWatcherCurrentLevelPrice)


@pytest.mark.asyncio
async def test_energy_sensor_initialization(hass, basic_config, mock_coordinator):
    """Test GridCapWatcherEnergySensor initialization."""
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    
    assert sensor.name == "Energy used this hour"
    assert sensor._effect_sensor_id == "sensor.power_meter"
    assert sensor._precision == 2
    assert sensor._state is None
    assert sensor.available is True
    assert sensor.native_value is None
    assert sensor.icon == "mdi:lightning-bolt"


@pytest.mark.asyncio
async def test_energy_sensor_properties(hass, basic_config, mock_coordinator):
    """Test GridCapWatcherEnergySensor properties."""
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    sensor._state = 3.456789
    
    assert sensor.native_value == 3.46
    assert sensor.unique_id == "energytariff_power_meter_consumption_kWh"


@pytest.mark.asyncio
async def test_energy_sensor_hourly_reset(hass, basic_config, mock_coordinator):
    """Test hourly reset functionality."""
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    sensor._state = 5.5
    sensor.async_schedule_update_ha_state = Mock()
    
    sensor.hourly_reset(dt.now())
    
    assert sensor._state == 0
    assert sensor.async_schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_energy_sensor_state_change(hass, basic_config, mock_coordinator):
    """Test energy sensor state change callback."""
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    sensor.async_schedule_update_ha_state = Mock()
    
    # Create mock states
    old_state = Mock()
    old_state.state = "1000"  # 1000W
    old_state.attributes = {"unit_of_measurement": "W"}
    old_state.last_updated = dt.now() - timedelta(seconds=1800)  # 30 minutes ago
    
    new_state = Mock()
    new_state.state = "1000"
    new_state.attributes = {"unit_of_measurement": "W"}
    new_state.last_updated = dt.now()
    
    # Create event
    event_data = {"old_state": old_state, "new_state": new_state}
    event = Mock(spec=Event)
    event.data = event_data
    
    sensor._async_on_change(event)
    
    # 1000W for 30 minutes = 0.5 kWh
    assert sensor._state is not None
    assert sensor._state > 0
    assert sensor.async_schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_energy_sensor_ignores_unavailable_state(hass, basic_config, mock_coordinator):
    """Test that sensor ignores unavailable states."""
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    sensor._state = 1.0
    
    old_state = Mock()
    old_state.state = STATE_UNAVAILABLE
    
    new_state = Mock()
    new_state.state = "1000"
    
    event_data = {"old_state": old_state, "new_state": new_state}
    event = Mock(spec=Event)
    event.data = event_data
    
    sensor._async_on_change(event)
    
    # State should remain unchanged
    assert sensor._state == 1.0


@pytest.mark.asyncio
async def test_estimated_energy_sensor_initialization(hass, basic_config, mock_coordinator):
    """Test GridCapWatcherEstimatedEnergySensor initialization."""
    sensor = GridCapWatcherEstimatedEnergySensor(hass, basic_config, mock_coordinator)
    
    assert sensor.name == "Energy estimate this hour"
    assert sensor._state is None
    assert sensor.available is True
    assert sensor.icon == "mdi:lightning-bolt"


@pytest.mark.asyncio
async def test_estimated_energy_sensor_state_change(hass, basic_config, mock_coordinator):
    """Test estimated energy sensor state change."""
    sensor = GridCapWatcherEstimatedEnergySensor(hass, basic_config, mock_coordinator)
    sensor.schedule_update_ha_state = Mock()
    
    # Create energy data: 2 kWh consumed, 1000W current power, 30 minutes remaining
    timestamp = dt.now() - timedelta(minutes=30)
    energy_data = EnergyData(2.0, 1000.0, timestamp)
    
    sensor._state_change(energy_data)
    
    # Should estimate: 2 kWh + (1000W * 1800s / 3600 / 1000) = 2 + 0.5 = 2.5 kWh
    assert sensor._state is not None
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_average_peak_hours_initialization(hass, basic_config, mock_coordinator):
    """Test GridCapWatcherAverageThreePeakHours initialization."""
    sensor = GridCapWatcherAverageThreePeakHours(hass, basic_config, mock_coordinator)
    
    assert sensor.name == "Average peak hour energy"
    assert sensor._state is None
    assert sensor.attr["top_three"] == []


@pytest.mark.asyncio
async def test_average_peak_hours_state_change(hass, basic_config, mock_coordinator):
    """Test average peak hours state change."""
    sensor = GridCapWatcherAverageThreePeakHours(hass, basic_config, mock_coordinator)
    sensor.schedule_update_ha_state = Mock()
    
    # Manually set up top three hours
    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 5.0},
        {"day": 2, "hour": 11, "energy": 6.0},
        {"day": 3, "hour": 12, "energy": 7.0},
    ]
    
    timestamp = dt.now()
    energy_data = EnergyData(4.0, 1000.0, timestamp)
    
    sensor._state_change(energy_data)
    
    # Average of current top_three values
    assert sensor._state is not None
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_available_effect_sensor_initialization(hass, config_with_limits, mock_coordinator):
    """Test GridCapWatcherAvailableEffectRemainingHour initialization."""
    sensor = GridCapWatcherAvailableEffectRemainingHour(
        hass, config_with_limits, mock_coordinator
    )
    
    assert sensor.name == "Available power this hour"
    assert sensor._state is None
    assert sensor._target_energy == 5.0
    assert sensor._max_effect == 10000.0


@pytest.mark.asyncio
async def test_available_effect_calculation(hass, config_with_limits, mock_coordinator):
    """Test available effect calculation."""
    sensor = GridCapWatcherAvailableEffectRemainingHour(
        hass, config_with_limits, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()
    
    # Set energy consumed to 2 kWh, current effect 1000W
    energy_data = EnergyData(2.0, 1000.0, dt.now())
    sensor._effect_state_change(energy_data)
    
    # Should have calculated available power
    assert sensor._state is not None
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_threshold_sensor_initialization(hass, config_with_levels, mock_coordinator):
    """Test GridCapWatcherCurrentEffectLevelThreshold initialization."""
    sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    
    assert sensor.name == "Energy level upper threshold"
    assert sensor._state is None
    assert len(sensor._levels) == 3


@pytest.mark.asyncio
async def test_threshold_sensor_get_level(hass, config_with_levels, mock_coordinator):
    """Test threshold level calculation."""
    sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    
    # Test getting correct level for different averages
    level = sensor.get_level(1.5)
    assert level["name"] == "Low"
    assert level["threshold"] == 2.0
    
    level = sensor.get_level(3.0)
    assert level["name"] == "Medium"
    assert level["threshold"] == 5.0
    
    level = sensor.get_level(6.0)
    assert level["name"] == "High"
    assert level["threshold"] == 8.0


@pytest.mark.asyncio
async def test_threshold_sensor_calculate_level(hass, config_with_levels, mock_coordinator):
    """Test threshold level calculation with top three hours."""
    sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()
    
    # Set top three hours averaging to 3 kWh
    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 2.0},
        {"day": 2, "hour": 11, "energy": 3.0},
        {"day": 3, "hour": 12, "energy": 4.0},
    ]
    
    sensor.calculate_level()
    
    # Average is 3.0, so should be "Medium" level with threshold 5.0
    assert sensor._state == 5.0
    assert sensor.schedule_update_ha_state.called

@pytest.mark.asyncio
async def test_threshold_sensor_calculate_level_repro(hass, config_with_levels, mock_coordinator):
    """Test threshold level calculation with top three hours."""
    sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()
    
    # Set top three hours averaging to 3 kWh
    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 6.902},
        {"day": 2, "hour": 11, "energy": 5.1978},
        {"day": 3, "hour": 12, "energy": 5.487},
    ]
    
    sensor.calculate_level()
    
    # Average is 5.86, so should be level with threshold 8.0
    assert sensor._state == 8.0
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_level_name_sensor_initialization(hass, config_with_levels, mock_coordinator):
    """Test GridCapacityWatcherCurrentLevelName initialization."""
    sensor = GridCapacityWatcherCurrentLevelName(
        hass, config_with_levels, mock_coordinator
    )
    
    assert sensor.name == "Energy level name"
    assert sensor._state is None
    assert sensor.icon == "mdi:rename-box"


@pytest.mark.asyncio
async def test_level_name_sensor_threshold_change(hass, config_with_levels, mock_coordinator):
    """Test level name sensor responds to threshold changes."""
    sensor = GridCapacityWatcherCurrentLevelName(
        hass, config_with_levels, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()
    
    threshold_data = GridThresholdData("Medium", 5.0, 100, [])
    sensor._threshold_state_change(threshold_data)
    
    assert sensor._state == "Medium"
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_level_price_sensor_initialization(hass, config_with_levels, mock_coordinator):
    """Test GridCapacityWatcherCurrentLevelPrice initialization."""
    sensor = GridCapacityWatcherCurrentLevelPrice(
        hass, config_with_levels, mock_coordinator
    )
    
    assert sensor.name == "Energy level price"
    assert sensor._state is None
    assert sensor.icon == "mdi:cash"


@pytest.mark.asyncio
async def test_level_price_sensor_threshold_change(hass, config_with_levels, mock_coordinator):
    """Test level price sensor responds to threshold changes."""
    sensor = GridCapacityWatcherCurrentLevelPrice(
        hass, config_with_levels, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()
    
    threshold_data = GridThresholdData("High", 8.0, 200, [])
    sensor._threshold_state_change(threshold_data)
    
    assert sensor._state == 200
    assert sensor.schedule_update_ha_state.called


@pytest.mark.asyncio
async def test_sensor_unique_ids(hass, basic_config, mock_coordinator):
    """Test that all sensors have unique IDs."""
    energy_sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    estimated_sensor = GridCapWatcherEstimatedEnergySensor(
        hass, basic_config, mock_coordinator
    )
    average_sensor = GridCapWatcherAverageThreePeakHours(
        hass, basic_config, mock_coordinator
    )
    available_sensor = GridCapWatcherAvailableEffectRemainingHour(
        hass, basic_config, mock_coordinator
    )
    
    unique_ids = [
        energy_sensor.unique_id,
        estimated_sensor.unique_id,
        average_sensor.unique_id,
        available_sensor.unique_id,
    ]
    
    # All unique IDs should be different
    assert len(unique_ids) == len(set(unique_ids))


@pytest.mark.asyncio
async def test_sensor_units_of_measurement(hass, basic_config, config_with_limits, mock_coordinator):
    """Test that sensors have correct units of measurement."""
    energy_sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)
    estimated_sensor = GridCapWatcherEstimatedEnergySensor(
        hass, basic_config, mock_coordinator
    )
    available_sensor = GridCapWatcherAvailableEffectRemainingHour(
        hass, config_with_limits, mock_coordinator
    )
    
    assert energy_sensor._attr_native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
    assert estimated_sensor._attr_native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
    assert available_sensor._attr_native_unit_of_measurement == UnitOfPower.WATT


# ---------------------------------------------------------------------------
# Regression and bug tests — these should FAIL on unfixed 0.3.0 code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regression_a_exceeds_all_levels(hass, mock_coordinator):
    """Regression A (P0 — 0.3.0 silent data loss):
    When GRID_LEVELS is configured and consumption exceeds ALL configured
    thresholds, GridCapWatcherCurrentEffectLevelThreshold.get_level() returns
    None and never calls thresholddata.on_next().
    GridCapWatcherAverageThreePeakHours._state_change() short-circuits when
    levels are configured (returns None immediately), so it never independently
    calculates top_three either.  The result: the avg sensor goes permanently
    stale — top_three stays [] and _state stays None.

    Correct behaviour: after 3 hours of consumption that each exceed the max
    configured threshold, the avg sensor's top_three must contain 3 entries and
    _state must be non-None.
    """
    config = {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Low", "threshold": 2.0, "price": 50},
            {"name": "Medium", "threshold": 5.0, "price": 100},
        ],
    }

    threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config, mock_coordinator
    )
    avg_sensor = GridCapWatcherAverageThreePeakHours(hass, config, mock_coordinator)

    threshold_sensor.schedule_update_ha_state = Mock()
    avg_sensor.schedule_update_ha_state = Mock()

    # Feed 3 hours across 3 different days — all 7.0 kWh, exceeding the 5.0 max level.
    base_ts = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    for day in [1, 2, 3]:
        energy_data = EnergyData(7.0, 7000.0, base_ts.replace(day=day))
        mock_coordinator.effectstate.on_next(energy_data)

    # The avg sensor must have recorded the three peak hours.
    assert len(avg_sensor.attr["top_three"]) == 3, (
        f"Expected 3 entries in avg_sensor top_three, got "
        f"{len(avg_sensor.attr['top_three'])}. "
        "Bug: _state_change short-circuits when levels configured, and threshold "
        "sensor never broadcasts when consumption exceeds all levels — avg sensor "
        "goes permanently stale."
    )
    assert avg_sensor._state is not None, (
        "Avg sensor _state must not be None after 3 hours of data."
    )


@pytest.mark.asyncio
async def test_regression_b_reference_not_copy(hass, config_with_levels, mock_coordinator):
    """Regression B (P0 — 0.3.0 reference assignment fragility):
    GridCapWatcherAverageThreePeakHours._threshold_state_change does:
        self.attr['top_three'] = threshold_data.top_three   # reference, not copy
    After this assignment both sensors share the same mutable list object.
    Any in-place mutation of the original list (e.g. list.clear(), list.sort(),
    or item assignment by calculate_top_three) silently affects the avg sensor's
    data too.

    Correct behaviour: the avg sensor must keep its OWN independent copy of
    top_three.  Mutating the originating list must not change the avg sensor's
    data.
    """
    avg_sensor = GridCapWatcherAverageThreePeakHours(
        hass, config_with_levels, mock_coordinator
    )
    avg_sensor.schedule_update_ha_state = Mock()

    # Build a top_three list and broadcast it to the avg sensor via thresholddata.
    source_list = [
        {"day": 1, "hour": 10, "energy": 3.0},
        {"day": 2, "hour": 11, "energy": 4.0},
        {"day": 3, "hour": 12, "energy": 5.0},
    ]
    mock_coordinator.thresholddata.on_next(
        GridThresholdData("Medium", 5.0, 100, source_list)
    )

    # Sanity-check: avg sensor should have received the three peaks.
    assert len(avg_sensor.attr["top_three"]) == 3

    # Now mutate the original list in-place (simulates what calculate_top_three
    # does via .sort() / item assignment, or what _async_reset_meter triggers
    # indirectly when the shared object is cleared before rebinding).
    source_list.clear()

    # avg sensor must NOT be affected — it should hold its own independent copy.
    assert len(avg_sensor.attr["top_three"]) == 3, (
        "avg_sensor top_three was silently wiped when the source list was cleared. "
        "Bug: _threshold_state_change assigns a reference "
        "(self.attr['top_three'] = threshold_data.top_three) instead of a copy. "
        "Fix: self.attr['top_three'] = list(threshold_data.top_three)"
    )


def test_bug_a_month_collision_in_calculate_top_three():
    """Bug A (P1 — pre-existing):
    calculate_top_three stores only 'day' (1–31), not 'month'.  If the
    monthly reset is missed (HA was down at the calendar boundary), old-month
    entries persist.  When the same day number reappears in the new month,
    calculate_top_three treats it as the *same* entry and either ignores the
    new reading (if lower) or overwrites the old one (if higher).  The months
    are never kept independent.

    Correct behaviour: a February day-5 reading must be treated as independent
    from a January day-5 entry.  After the fix, each entry carries a 'month'
    field and the collision check uses (month, day), so both months' data
    coexist in top_three rather than shadowing each other.
    """
    from custom_components.energytariff.utils import calculate_top_three

    # January day 5, high consumption.
    jan_ts = datetime(2025, 1, 5, 8, 0, 0, tzinfo=timezone.utc)
    jan_energy = EnergyData(5.0, 5000.0, jan_ts)

    top_three = []
    top_three = calculate_top_three(jan_energy, top_three)

    assert len(top_three) == 1
    assert top_three[0]["day"] == 5

    # Monthly reset was missed — top_three still contains the January entry.
    # February day 5 arrives with a lower energy value (2.0 kWh).
    feb_ts = datetime(2025, 2, 5, 9, 0, 0, tzinfo=timezone.utc)
    feb_energy = EnergyData(2.0, 2000.0, feb_ts)

    top_three = calculate_top_three(feb_energy, top_three)

    # The February entry must be represented independently (carries month=2).
    # Currently FAILS because calculate_top_three only checks 'day', so Feb day-5
    # collides with Jan day-5.  Since 2.0 < 5.0 the Feb reading is silently ignored
    # and 'month' is never stored.
    assert any(
        e.get("month") == 2 and int(e["day"]) == 5 for e in top_three
    ), (
        f"No February (month=2) day-5 entry found in top_three: {top_three}. "
        "Bug: calculate_top_three uses only 'day' for collision detection, so "
        "February day-5 shadows/matches January day-5 instead of being tracked "
        "independently."
    )

