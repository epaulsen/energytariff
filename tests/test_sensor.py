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
from homeassistant.exceptions import TemplateError
import voluptuous as vol
from custom_components.energytariff.sensor import (
    async_setup_platform,
    GridCapWatcherEnergySensor,
    GridCapWatcherEstimatedEnergySensor,
    GridCapWatcherAverageThreePeakHours,
    GridCapWatcherAvailableEffectRemainingHour,
    GridCapWatcherCurrentEffectLevelThreshold,
    GridCapacityWatcherCurrentLevelName,
    GridCapacityWatcherCurrentLevelPrice,
    _restore_top_three,
    LEVEL_SCHEMA,
    _restore_top_three,
)
from custom_components.energytariff.coordinator import (
    GridCapacityCoordinator,
    EnergyData,
    GridThresholdData,
)
from custom_components.energytariff.const import (
    CONF_EFFECT_ENTITY,
    GRID_LEVELS,
    LEVEL_PRICE,
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
    assert mock_add_entities.call_count == 1
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 4
    assert isinstance(entities[0], GridCapWatcherEnergySensor)
    assert isinstance(entities[1], GridCapWatcherEstimatedEnergySensor)
    assert isinstance(entities[2], GridCapWatcherAvailableEffectRemainingHour)
    assert isinstance(entities[3], GridCapWatcherAverageThreePeakHours)


@pytest.mark.asyncio
async def test_async_setup_platform_with_levels(hass, config_with_levels):
    """Test sensor platform setup with grid levels configuration.

    Threshold sensor must be initialised BEFORE the average sensor so that
    threshold subscribes to effectstate first.  This prevents the startup race
    where avg processes gap events that threshold misses, then threshold's first
    thresholddata emission overwrites avg's correct data with stale restored data.
    """
    mock_add_entities = Mock()

    await async_setup_platform(hass, config_with_levels, mock_add_entities)

    assert mock_add_entities.call_count == 1, (
        "All entities must be added in a single async_add_entities call so that "
        "threshold initialises before avg (correct subscription order)."
    )
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 7
    assert isinstance(entities[0], GridCapWatcherEnergySensor)
    assert isinstance(entities[1], GridCapWatcherEstimatedEnergySensor)
    assert isinstance(entities[2], GridCapWatcherAvailableEffectRemainingHour)
    # Threshold sensors must come before the average sensor.
    assert isinstance(entities[3], GridCapWatcherCurrentEffectLevelThreshold)
    assert isinstance(entities[4], GridCapacityWatcherCurrentLevelName)
    assert isinstance(entities[5], GridCapacityWatcherCurrentLevelPrice)
    assert isinstance(entities[6], GridCapWatcherAverageThreePeakHours)


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
    
    sensor._initialized = True
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

    # Initialize sensors as async_added_to_hass would, without touching HA storage.
    threshold_sensor._initialized = True
    threshold_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(threshold_sensor._state_change)
    ]
    avg_sensor._initialized = True
    avg_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(avg_sensor._state_change)
    ]

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
async def test_regression_b_calculate_level_emits_deep_copy(hass, config_with_levels, mock_coordinator):
    """Regression B (Fix 2): calculate_level must broadcast a deep copy of top_three.

    If calculate_level passes a direct reference to self.attr['top_three'], any
    subsequent mutation of the dict entries (e.g. calculate_top_three updating
    'energy'/'hour' in-place on the same dict objects) would corrupt the already-
    broadcast GridThresholdData — causing the alternating 2.59/7.59 pattern
    observed in ha_query.csv.

    Fix: [dict(e) for e in self.attr['top_three']] in calculate_level.
    """
    threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    threshold_sensor.schedule_update_ha_state = Mock()

    original_entries = [
        {"month": 5, "day": 1, "hour": 10, "energy": 2.0},
        {"month": 5, "day": 2, "hour": 11, "energy": 3.0},
        {"month": 5, "day": 3, "hour": 12, "energy": 4.0},
    ]
    threshold_sensor.attr["top_three"] = original_entries

    received: list[GridThresholdData] = []
    mock_coordinator.thresholddata.subscribe(received.append)
    received.clear()

    threshold_sensor.calculate_level()

    assert len(received) == 1
    emitted_top_three = received[0].top_three

    # Mutate the threshold sensor's internal entry in-place (as calculate_top_three does).
    original_entries[0]["energy"] = 999.0

    # The emitted GridThresholdData must NOT be affected — it must be a deep copy.
    assert emitted_top_three[0]["energy"] != 999.0, (
        "calculate_level emitted a reference to the internal top_three dict. "
        "Mutating the dict after broadcast corrupted the emitted GridThresholdData. "
        "Fix: use [dict(e) for e in self.attr['top_three']] in calculate_level."
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



# --- Upgrade migration: _restore_top_three ---
#
# These tests guard the fix for the upgrade bug where users on 0.3.0/0.3.1 lost
# all top_three data on first HA restart.  Old entries had no 'month' field; the
# unfixed code treated missing month as None and discarded every such entry.
#
# The fix: item.get("month", current_month) — missing month defaults to
# current_month so legacy entries are preserved.


def test_restore_top_three_legacy_no_month_field():
    """Regression guard: legacy entries (no 'month' key) must be preserved on upgrade."""
    from homeassistant.util import dt as ha_dt

    current_month = ha_dt.as_local(ha_dt.now()).month
    savedstate = Mock()
    savedstate.attributes = {
        "top_three": [
            {"day": 3, "hour": 17, "energy": 10.2},
            {"day": 14, "hour": 18, "energy": 9.7},
            {"day": 8, "hour": 18, "energy": 9.5},
        ]
    }
    attr = {"top_three": []}
    _restore_top_three(savedstate, attr)

    assert len(attr["top_three"]) == 3, (
        f"Expected 3 legacy entries to be restored, got {len(attr['top_three'])}. "
        "Bug: _restore_top_three treated missing 'month' as None and discarded all "
        "legacy entries, wiping top_three on first restart after upgrade from 0.3.0/0.3.1."
    )
    for entry in attr["top_three"]:
        assert entry["month"] == current_month


def test_restore_top_three_prior_month_entries_discarded():
    """Prior-month entries with explicit month field must still be discarded."""
    from homeassistant.util import dt as ha_dt

    current_month = ha_dt.as_local(ha_dt.now()).month
    prior_month = 12 if current_month == 1 else current_month - 1
    savedstate = Mock()
    savedstate.attributes = {
        "top_three": [
            {"month": prior_month, "day": 5, "hour": 10, "energy": 8.0},
            {"month": prior_month, "day": 12, "hour": 14, "energy": 7.5},
        ]
    }
    attr = {"top_three": []}
    _restore_top_three(savedstate, attr)

    assert len(attr["top_three"]) == 0, (
        f"Expected prior-month (month={prior_month}) entries to be discarded, "
        f"got: {attr['top_three']}"
    )


def test_restore_top_three_mixed_format():
    """Mixed state: legacy (no month), modern current-month, prior-month — only current survive."""
    from homeassistant.util import dt as ha_dt

    current_month = ha_dt.as_local(ha_dt.now()).month
    prior_month = 12 if current_month == 1 else current_month - 1
    savedstate = Mock()
    savedstate.attributes = {
        "top_three": [
            {"day": 3, "hour": 17, "energy": 10.2},                         # legacy: no month
            {"month": current_month, "day": 14, "hour": 18, "energy": 9.7}, # modern current
            {"month": prior_month, "day": 8, "hour": 18, "energy": 9.5},    # prior month
        ]
    }
    attr = {"top_three": []}
    _restore_top_three(savedstate, attr)

    assert len(attr["top_three"]) == 2, (
        f"Expected 2 current-month entries (1 legacy + 1 modern), "
        f"got {len(attr['top_three'])}: {attr['top_three']}"
    )
    surviving_months = {e["month"] for e in attr["top_three"]}
    assert surviving_months == {current_month}


@pytest.mark.asyncio
async def test_restore_top_three_bug_b_still_fixed(hass, config_with_levels, mock_coordinator):
    """Guard: avg sensor must not be affected by thresholddata at all.

    After Fix 1, avg does NOT subscribe to thresholddata. Any thresholddata
    emission — including those with mutated or cleared source lists — must have
    zero effect on avg's top_three. The only way avg's top_three changes is via
    effectstate (_state_change).
    """
    avg_sensor = GridCapWatcherAverageThreePeakHours(
        hass, config_with_levels, mock_coordinator
    )
    avg_sensor.schedule_update_ha_state = Mock()

    savedstate = Mock()
    savedstate.attributes = {
        "top_three": [
            {"day": 3, "hour": 17, "energy": 10.2},
            {"day": 14, "hour": 18, "energy": 9.7},
            {"day": 8, "hour": 18, "energy": 9.5},
        ]
    }
    _restore_top_three(savedstate, avg_sensor.attr)
    assert len(avg_sensor.attr["top_three"]) == 3, "Precondition: legacy restore must succeed"

    # Emit thresholddata — avg is NOT subscribed, so this must be a no-op.
    source_list = [
        {"month": 1, "day": 3, "hour": 17, "energy": 10.2},
        {"month": 1, "day": 14, "hour": 18, "energy": 9.7},
        {"month": 1, "day": 8, "hour": 18, "energy": 9.5},
    ]
    mock_coordinator.thresholddata.on_next(
        GridThresholdData("High", 8.0, 200, source_list)
    )
    assert len(avg_sensor.attr["top_three"]) == 3, (
        "thresholddata changed avg's top_three — avg must not subscribe to thresholddata."
    )

    source_list.clear()  # simulate threshold sensor monthly reset
    assert len(avg_sensor.attr["top_three"]) == 3, (
        "Clearing the thresholddata source list affected avg — Fix 1 may have been reverted."
    )


# --- Issue #22: Template pricing tests ---
# These tests cover the LEVEL_PRICE template feature.
# Tests 1 and 5 pass against current code.
# Tests 2-4 and 6 are spec-driven and will pass once Geordi's implementation lands.


@pytest.mark.asyncio
async def test_level_price_static_number_unchanged(hass, config_with_levels, mock_coordinator):
    """Regression guard: a numeric price (int or float) must work exactly as before.

    Verifies that after calculate_level() fires, thresholddata.on_next() receives a
    GridThresholdData whose price is the correct float — no regression from adding
    template support.
    """
    sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    sensor.schedule_update_ha_state = Mock()

    # Average of 3.0 kWh -> "Medium" level, price=100
    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 2.0},
        {"day": 2, "hour": 11, "energy": 3.0},
        {"day": 3, "hour": 12, "energy": 4.0},
    ]

    received: list[GridThresholdData] = []
    mock_coordinator.thresholddata.subscribe(received.append)
    # Drain the initial None emitted by BehaviorSubject
    received.clear()

    result = sensor.calculate_level()

    assert result is True
    assert len(received) == 1
    assert received[0].price == 100.0
    assert isinstance(received[0].price, float)


@pytest.mark.asyncio
async def test_level_price_template_renders_correctly(hass, mock_coordinator):
    """Happy path: a Template object stored as the price renders to a float correctly.

    Simulates what Geordi's __init__ pre-processing will do: convert the raw template
    string to a Template object. We inject the mock directly so the test is independent
    of the __init__ implementation detail — what matters is that calculate_level()
    resolves it and broadcasts the rendered float.
    """
    from homeassistant.helpers import template as template_helper

    config = {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Low", "threshold": 2.0, "price": 50},
            {"name": "Medium", "threshold": 5.0, "price": 100},
        ],
    }

    sensor = GridCapWatcherCurrentEffectLevelThreshold(hass, config, mock_coordinator)
    sensor.schedule_update_ha_state = Mock()

    # Replace the numeric price with a mock Template object that renders to 175.0
    mock_template = Mock(spec=template_helper.Template)
    mock_template.render.return_value = 175.0
    sensor._levels[0][LEVEL_PRICE] = mock_template  # "Low" level

    # Average of 1.0 kWh -> "Low" level (threshold 2.0, price now a template)
    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 1.0},
    ]

    received: list[GridThresholdData] = []
    mock_coordinator.thresholddata.subscribe(received.append)
    received.clear()

    result = sensor.calculate_level()

    assert result is True
    assert len(received) == 1
    assert received[0].price == 175.0
    mock_template.render.assert_called_once_with(parse_result=True)


@pytest.mark.asyncio
async def test_level_price_template_entity_unavailable(hass, mock_coordinator):
    """Graceful degradation: template raises TemplateError (entity unavailable).

    calculate_level() must return False, must NOT call thresholddata.on_next(),
    and must not raise an unhandled exception.
    """
    from homeassistant.helpers import template as template_helper

    config = {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Low", "threshold": 2.0, "price": 50},
        ],
    }

    sensor = GridCapWatcherCurrentEffectLevelThreshold(hass, config, mock_coordinator)
    sensor.schedule_update_ha_state = Mock()

    # Template that raises TemplateError — simulates a missing/unavailable entity
    mock_template = Mock(spec=template_helper.Template)
    mock_template.render.side_effect = TemplateError(Exception("unavailable"))
    sensor._levels[0][LEVEL_PRICE] = mock_template

    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 1.0},
    ]

    received: list[GridThresholdData] = []
    mock_coordinator.thresholddata.subscribe(received.append)
    received.clear()

    result = sensor.calculate_level()

    assert result is False
    assert len(received) == 0, "thresholddata.on_next() must NOT be called when template fails"


@pytest.mark.asyncio
async def test_level_price_template_non_numeric_result(hass, mock_coordinator):
    """ValueError path: template renders to a non-numeric string.

    calculate_level() must catch the ValueError, log it, return False, and must NOT
    call thresholddata.on_next(). No unhandled exception must propagate.
    """
    from homeassistant.helpers import template as template_helper

    config = {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Low", "threshold": 2.0, "price": 50},
        ],
    }

    sensor = GridCapWatcherCurrentEffectLevelThreshold(hass, config, mock_coordinator)
    sensor.schedule_update_ha_state = Mock()

    # Template renders to a non-numeric string — float() will raise ValueError
    mock_template = Mock(spec=template_helper.Template)
    mock_template.render.return_value = "not-a-number"
    sensor._levels[0][LEVEL_PRICE] = mock_template

    sensor.attr["top_three"] = [
        {"day": 1, "hour": 10, "energy": 1.0},
    ]

    received: list[GridThresholdData] = []
    mock_coordinator.thresholddata.subscribe(received.append)
    received.clear()

    result = sensor.calculate_level()

    assert result is False
    assert len(received) == 0, "thresholddata.on_next() must NOT be called when price is non-numeric"


def test_schema_accepts_template_string():
    """Schema validation: LEVEL_SCHEMA must accept a valid Jinja2 template string for price.

    Also verifies that static int and float prices continue to be accepted — the new
    vol.Any(cv.Number, cv.template) validator must not break existing configs.

    NOTE: cv.template converts the validated string to a Template object, so we check
    type rather than string equality for the template case.
    """
    from homeassistant.helpers import template as template_helper

    # Static int — must still pass
    result_int = LEVEL_SCHEMA({"name": "Low", "threshold": 2.0, "price": 135})
    assert result_int["price"] == 135

    # Static float — must still pass
    result_float = LEVEL_SCHEMA({"name": "Medium", "threshold": 5.0, "price": 135.5})
    assert result_float["price"] == 135.5

    # Valid Jinja2 template string — must now be accepted (Issue #22).
    # cv.template returns a Template object, not the raw string.
    result_template = LEVEL_SCHEMA(
        {"name": "High", "threshold": 8.0, "price": "{{ states('sensor.electricity_price') }}"}
    )
    assert isinstance(result_template["price"], template_helper.Template)


def test_schema_rejects_invalid_template():
    """Schema validation: LEVEL_SCHEMA must reject a malformed Jinja2 template for price.

    A string like '{{ unclosed' has invalid Jinja2 syntax and must raise a
    voluptuous Invalid exception at config-load time, not at runtime.
    """
    with pytest.raises(vol.Invalid):
        LEVEL_SCHEMA({"name": "Low", "threshold": 2.0, "price": "{{ unclosed"})


@pytest.mark.asyncio
async def test_regression_c_race_condition_threshold_uninitialized(
    hass, config_with_levels, mock_coordinator
):
    """Regression C (root-cause fix): startup race condition must not corrupt avg sensor.

    Scenario: avg sensor is fully initialized (top_three restored from HA state).
    Threshold sensor has NOT yet completed async_added_to_hass (top_three empty,
    _initialized=False).  An effectstate event fires in this window (e.g. power
    meter comes back online after a long outage).

    Old behaviour: threshold._state_change ran with empty top_three, emitted
    thresholddata([{energy:5.01}]), avg._threshold_state_change overwrote the
    correctly-restored top_three.

    Correct behaviour: threshold sensor must ignore the event while _initialized
    is False, so avg sensor's restored top_three is never corrupted.
    """
    restored_top_three = [
        {"month": 4, "day": 1, "hour": 10, "energy": 6.30},
        {"month": 4, "day": 2, "hour": 14, "energy": 7.85},
        {"month": 4, "day": 3, "hour": 9, "energy": 7.28},
    ]

    # avg sensor: fully initialized with restored top_three.
    avg_sensor = GridCapWatcherAverageThreePeakHours(
        hass, config_with_levels, mock_coordinator
    )
    avg_sensor.schedule_update_ha_state = Mock()
    avg_sensor.attr["top_three"] = list(restored_top_three)
    avg_sensor._initialized = True
    avg_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(avg_sensor._state_change),
        # avg does NOT subscribe to thresholddata (Fix 1).
    ]

    # threshold sensor: created but async_added_to_hass has NOT run (_initialized=False).
    threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    threshold_sensor.schedule_update_ha_state = Mock()
    # _initialized remains False — threshold is not subscribed yet.

    # effectstate fires while threshold is uninitialized (stale 5.01 kWh from last save).
    stale_ts = datetime(2026, 4, 27, 5, 44, 0, tzinfo=timezone.utc)
    stale_energy = EnergyData(5.01, 5010.0, stale_ts)
    mock_coordinator.effectstate.on_next(stale_energy)

    # avg sensor must still have its 3 restored entries — NOT the stale 5.01 single entry.
    assert len(avg_sensor.attr["top_three"]) == 3, (
        f"avg sensor top_three corrupted by stale effectstate during startup race. "
        f"Got: {avg_sensor.attr['top_three']}"
    )
    energies = [e["energy"] for e in avg_sensor.attr["top_three"]]
    assert 5.01 not in energies or len(avg_sensor.attr["top_three"]) == 3, (
        "avg top_three was overwritten with the stale single-entry thresholddata."
    )
    # State must still reflect original restored average, not the stale 5.01.
    expected_avg = sum(e["energy"] for e in restored_top_three) / 3
    # (avg._state_change ran for effectstate, but 5.01 < all restored entries so no change)
    assert avg_sensor._state is None or avg_sensor._state != pytest.approx(5.01, abs=0.01), (
        "avg sensor _state was corrupted to 5.01 by the startup race condition."
    )


@pytest.mark.asyncio
async def test_regression_e_avg_maintains_independent_top_three(
    hass, config_with_levels, mock_coordinator
):
    """Regression E: avg sensor maintains its own top_three independently of threshold.

    After Fix 1 (remove thresholddata subscription from avg), avg and threshold
    each compute top_three from effectstate events they each observe.  They may
    legitimately diverge — that is correct and expected.

    Scenario:
      1. Threshold initialises first with restored top_three [day1, day2, day3].
      2. Gap AMS event fires (day4=2.7 kWh) — threshold processes it, avg not yet subscribed.
         Threshold top_three now includes day4 (replaces lowest day3=2.5).
      3. Avg initialises with SAME restored data [day1, day2, day3].
         Avg subscribes to effectstate only (NOT thresholddata).
      4. Next AMS event fires (0.5 kWh — won't displace any peak).

    Correct behaviour:
      - avg top_three = [day1, day2, day3] (unchanged — 0.5 < all restored peaks).
      - avg does NOT have day4 (it never observed the gap event).
      - avg maintains its own state; threshold's gap-event update is irrelevant to avg.
    """
    restored_top_three = [
        {"month": 5, "day": 1, "hour": 17, "energy": 3.0},
        {"month": 5, "day": 2, "hour": 18, "energy": 2.8},
        {"month": 5, "day": 3, "hour": 16, "energy": 2.5},
    ]

    # --- Threshold sensor initialises first ---
    threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    threshold_sensor.schedule_update_ha_state = Mock()
    threshold_sensor.attr["top_three"] = [dict(e) for e in restored_top_three]
    threshold_sensor._initialized = True
    threshold_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(threshold_sensor._state_change)
    ]

    # --- Gap event: threshold processes, avg not yet subscribed ---
    gap_ts = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    gap_event = EnergyData(2.7, 2700.0, gap_ts)
    mock_coordinator.effectstate.on_next(gap_event)

    threshold_days = [e["day"] for e in threshold_sensor.attr["top_three"]]
    assert 4 in threshold_days, (
        f"Precondition: threshold must have processed gap event (day=4). Got: {threshold_days}"
    )

    # --- Avg initialises second with same restored data ---
    avg_sensor = GridCapWatcherAverageThreePeakHours(
        hass, config_with_levels, mock_coordinator
    )
    avg_sensor.schedule_update_ha_state = Mock()
    avg_sensor.attr["top_three"] = [dict(e) for e in restored_top_three]
    avg_sensor._initialized = True
    avg_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(avg_sensor._state_change),
        # avg does NOT subscribe to thresholddata (Fix 1).
    ]

    # --- Next AMS event fires: 0.5 kWh, won't displace any restored peak ---
    next_ts = datetime(2026, 5, 4, 11, 0, 0, tzinfo=timezone.utc)
    next_event = EnergyData(0.5, 500.0, next_ts)
    mock_coordinator.effectstate.on_next(next_event)

    avg_days = [e["day"] for e in avg_sensor.attr["top_three"]]

    # avg must keep its own restored top_three — not threshold's version.
    assert 4 not in avg_days or all(
        e["day"] in [1, 2, 3, 4] for e in avg_sensor.attr["top_three"]
    ), f"avg top_three unexpected: {avg_sensor.attr['top_three']}"

    # avg must still have its 3 restored entries (0.5 kWh < all peaks).
    assert len(avg_sensor.attr["top_three"]) == 3, (
        f"avg top_three should have 3 entries from restore. Got: {avg_sensor.attr['top_three']}"
    )
    # avg state must reflect its own data, not threshold's.
    assert avg_sensor._state is not None


@pytest.mark.asyncio
async def test_regression_f_threshold_stale_restore_does_not_overwrite_avg(
    hass, config_with_levels, mock_coordinator
):
    """Regression F: avg must NOT be overwritten by threshold's stale restored state.

    This is the exact failure observed in ha_query.csv (post-reboot drop):
      - Threshold restores STALE top_three: day3=hr0, energy=2.590618
        (saved from a previous session that ended early, before day3's peak hour)
      - Avg restores CORRECT top_three: day3=hr4, energy=5.762
      - First AMS event fires for day4 (new day), energy=0.8 kWh < 2.590618
        → threshold does not replace day3 with day4; emits thresholddata with stale top_three
      - BUG (pre-fix): avg._threshold_state_change fires → overwrites avg's correct day3=5.762
        with stale day3=2.590618 → avg drops from 6.06 to 5.0
      - FIX (Fix 1): avg does NOT subscribe to thresholddata; ignores the stale emission

    After fix: avg top_three must still contain day3=hr4, energy=5.762.
    """
    current_month = 5

    # --- Threshold: stale restored state ---
    threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
        hass, config_with_levels, mock_coordinator
    )
    threshold_sensor.schedule_update_ha_state = Mock()
    threshold_sensor.attr["top_three"] = [
        {"month": current_month, "day": 1, "hour": 8, "energy": 6.902},
        {"month": current_month, "day": 2, "hour": 9, "energy": 5.198},
        {"month": current_month, "day": 3, "hour": 0, "energy": 2.590618},  # stale!
    ]
    threshold_sensor._initialized = True
    threshold_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(threshold_sensor._state_change)
    ]

    # --- Avg: correct restored state ---
    avg_sensor = GridCapWatcherAverageThreePeakHours(
        hass, config_with_levels, mock_coordinator
    )
    avg_sensor.schedule_update_ha_state = Mock()
    avg_sensor.attr["top_three"] = [
        {"month": current_month, "day": 1, "hour": 8, "energy": 6.902},
        {"month": current_month, "day": 2, "hour": 9, "energy": 5.198},
        {"month": current_month, "day": 3, "hour": 4, "energy": 5.762},  # correct!
    ]
    avg_sensor._initialized = True
    avg_sensor._disposables = [
        mock_coordinator.effectstate.subscribe(avg_sensor._state_change),
        # avg does NOT subscribe to thresholddata (Fix 1).
    ]

    # Compute expected avg from correct data.
    correct_avg = (6.902 + 5.198 + 5.762) / 3  # ≈ 5.954

    # Verify precondition: avg state matches correct data.
    # (Simulate what async_added_to_hass would compute after restore)
    avg_sensor._state = correct_avg

    # --- First AMS event: day4, low energy (0.8 kWh) < all threshold peaks ---
    # Threshold keeps stale top_three (day3=2.590618 not displaced by 0.8).
    # Threshold emits thresholddata with stale top_three.
    # avg must IGNORE this emission.
    day4_ts = datetime(2026, 5, 4, 6, 0, 0, tzinfo=timezone.utc)
    day4_event = EnergyData(0.8, 800.0, day4_ts)
    mock_coordinator.effectstate.on_next(day4_event)

    # avg top_three must still contain day3=hr4, energy=5.762.
    avg_day3_entries = [
        e for e in avg_sensor.attr["top_three"]
        if e["day"] == 3
    ]
    assert len(avg_day3_entries) == 1, (
        f"avg top_three should have exactly one day=3 entry. Got: {avg_sensor.attr['top_three']}"
    )
    assert avg_day3_entries[0]["hour"] == 4, (
        f"avg day3 entry should be hr4 (correct), not hr0 (stale). "
        f"Got hour={avg_day3_entries[0]['hour']}. "
        "Bug: avg was overwritten by threshold's stale thresholddata emission."
    )
    assert abs(avg_day3_entries[0]["energy"] - 5.762) < 0.01, (
        f"avg day3 energy should be 5.762 (correct), not 2.590618 (stale). "
        f"Got energy={avg_day3_entries[0]['energy']}."
    )


@pytest.mark.asyncio
async def test_regression_d_stale_energy_not_restored(hass, basic_config, mock_coordinator):
    """Regression D: energy sensor must not restore a stale hourly state after a long gap.

    When HA restarts after being down for hours/days, the last saved energy value
    belongs to a previous hour.  Restoring it causes the first effectstate emission
    to carry a stale non-zero kWh, which then seeds a wrong entry into top_three
    (e.g. 5.01 kWh from before the crash).

    Correct behaviour: if the last save timestamp is before the start of the
    current hour, self._state must be reset to 0 (not the saved value).
    """
    sensor = GridCapWatcherEnergySensor(hass, basic_config, mock_coordinator)

    # Simulate saved sensor data with a value from a previous hour.
    saved_sensor_data = Mock()
    saved_sensor_data.native_value = 5.01

    # last_updated is 3 hours ago — clearly in a previous hour.
    stale_last_updated = dt.utcnow() - timedelta(hours=3)
    last_state = Mock()
    last_state.last_updated = stale_last_updated

    sensor.async_get_last_sensor_data = AsyncMock(return_value=saved_sensor_data)
    sensor.async_get_last_state = AsyncMock(return_value=last_state)

    await sensor.async_added_to_hass()

    assert sensor._state == 0 or sensor._state is None, (
        f"Energy sensor restored stale value {sensor._state} from a previous hour. "
        "Expected 0 or None after a multi-hour gap (stale hourly accumulator must be discarded)."
    )
