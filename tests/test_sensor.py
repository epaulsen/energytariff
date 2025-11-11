"""Test energytariff sensor platform."""
import pytest
from datetime import datetime, timedelta
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
def mock_coordinator(hass):
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
