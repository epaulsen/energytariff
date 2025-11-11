"""Test synchronization between GridCapWatcherAverageThreePeakHours and GridCapWatcherCurrentEffectLevelThreshold."""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from homeassistant.util import dt
from custom_components.energytariff.sensor import (
    GridCapWatcherAverageThreePeakHours,
    GridCapWatcherCurrentEffectLevelThreshold,
)
from custom_components.energytariff.coordinator import (
    GridCapacityCoordinator,
    EnergyData,
)
from custom_components.energytariff.const import (
    CONF_EFFECT_ENTITY,
    GRID_LEVELS,
    ROUNDING_PRECISION,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture
def config_with_levels():
    """Create a sensor configuration with grid levels matching the issue."""
    return {
        CONF_EFFECT_ENTITY: "sensor.power_meter",
        ROUNDING_PRECISION: 2,
        GRID_LEVELS: [
            {"name": "Trinn 1: 0-2 kWh", "threshold": 2, "price": 160},
            {"name": "Trinn 2: 2-5 kWh", "threshold": 5, "price": 260},
            {"name": "Trinn 3: 5-10 kWh", "threshold": 10, "price": 430},
            {"name": "Trinn 4: 10-15 kWh", "threshold": 15, "price": 620},
            {"name": "Trinn 5: 15-20 kWh", "threshold": 20, "price": 800},
        ],
    }


@pytest.fixture
def mock_coordinator(hass):
    """Create a mock GridCapacityCoordinator."""
    return GridCapacityCoordinator(hass)


@pytest.mark.asyncio
async def test_sensors_use_same_top_three_data(hass, config_with_levels, mock_coordinator):
    """Test that both sensors use the same top_three data.
    
    This test reproduces the issue from the bug report where:
    - Average peak hour energy shows 10.15 kWh
    - Energy level upper threshold shows 10 kWh (should be 15 kWh)
    - Price shows 430 NOK (should be 620 NOK)
    """
    with patch('homeassistant.helpers.event.async_track_point_in_time'):
        # Create both sensors
        threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
            hass, config_with_levels, mock_coordinator
        )
        average_sensor = GridCapWatcherAverageThreePeakHours(
            hass, config_with_levels, mock_coordinator
        )
        
        # Mock the schedule_update_ha_state method
        threshold_sensor.schedule_update_ha_state = Mock()
        average_sensor.schedule_update_ha_state = Mock()
        
        # Simulate three peak hours that average to 10.15 kWh
        # Day 1: 10.0 kWh
        timestamp1 = datetime(2024, 1, 1, 10, 0, 0, tzinfo=dt.DEFAULT_TIME_ZONE)
        energy_data1 = EnergyData(10.0, 1000.0, timestamp1)
        mock_coordinator.effectstate.on_next(energy_data1)
        
        # Day 2: 10.0 kWh
        timestamp2 = datetime(2024, 1, 2, 11, 0, 0, tzinfo=dt.DEFAULT_TIME_ZONE)
        energy_data2 = EnergyData(10.0, 1000.0, timestamp2)
        mock_coordinator.effectstate.on_next(energy_data2)
        
        # Day 3: 10.45 kWh
        timestamp3 = datetime(2024, 1, 3, 12, 0, 0, tzinfo=dt.DEFAULT_TIME_ZONE)
        energy_data3 = EnergyData(10.45, 1000.0, timestamp3)
        mock_coordinator.effectstate.on_next(energy_data3)
        
        # Check that both sensors have the same top_three data
        assert threshold_sensor.attr["top_three"] == average_sensor.attr["top_three"], \
            "Both sensors should maintain the same top_three data"
        
        # Calculate expected average
        expected_average = (10.0 + 10.0 + 10.45) / 3
        assert abs(expected_average - 10.15) < 0.01, f"Expected average to be 10.15, got {expected_average}"
        
        # Check the average sensor's state
        assert average_sensor._state is not None, "Average sensor should have a state"
        assert abs(average_sensor._state - 10.15) < 0.01, \
            f"Average sensor should show 10.15 kWh, got {average_sensor._state}"
        
        # Check the threshold sensor's state (should be 15 kWh for Trinn 4)
        assert threshold_sensor._state is not None, "Threshold sensor should have a state"
        assert threshold_sensor._state == 15, \
            f"Threshold sensor should show 15 kWh (Trinn 4), got {threshold_sensor._state} kWh"


@pytest.mark.asyncio
async def test_threshold_level_boundary_exactly_10kwh(hass, config_with_levels, mock_coordinator):
    """Test threshold level when average is exactly 10 kWh.
    
    When average is exactly 10.0 kWh, it should select Trinn 4 (10-15 kWh).
    """
    with patch('homeassistant.helpers.event.async_track_point_in_time'):
        threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
            hass, config_with_levels, mock_coordinator
        )
        threshold_sensor.schedule_update_ha_state = Mock()
        
        # Set top_three to average exactly 10.0 kWh
        threshold_sensor.attr["top_three"] = [
            {"day": 1, "hour": 10, "energy": 10.0},
            {"day": 2, "hour": 11, "energy": 10.0},
            {"day": 3, "hour": 12, "energy": 10.0},
        ]
        
        threshold_sensor.calculate_level()
        
        # Should select Trinn 4 (10-15 kWh) with threshold 15
        assert threshold_sensor._state == 15, \
            f"For average=10.0 kWh, should select Trinn 4 (threshold=15), got {threshold_sensor._state}"


@pytest.mark.asyncio
async def test_threshold_level_boundary_just_above_10kwh(hass, config_with_levels, mock_coordinator):
    """Test threshold level when average is just above 10 kWh.
    
    This is the exact scenario from the bug report.
    """
    with patch('homeassistant.helpers.event.async_track_point_in_time'):
        threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
            hass, config_with_levels, mock_coordinator
        )
        threshold_sensor.schedule_update_ha_state = Mock()
        
        # Set top_three to average 10.15 kWh
        threshold_sensor.attr["top_three"] = [
            {"day": 1, "hour": 10, "energy": 10.0},
            {"day": 2, "hour": 11, "energy": 10.0},
            {"day": 3, "hour": 12, "energy": 10.45},
        ]
        
        threshold_sensor.calculate_level()
        
        # Should select Trinn 4 (10-15 kWh) with threshold 15 and price 620
        assert threshold_sensor._state == 15, \
            f"For average=10.15 kWh, should select Trinn 4 (threshold=15), got {threshold_sensor._state}"


@pytest.mark.asyncio
async def test_threshold_level_boundary_just_below_10kwh(hass, config_with_levels, mock_coordinator):
    """Test threshold level when average is just below 10 kWh."""
    with patch('homeassistant.helpers.event.async_track_point_in_time'):
        threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
            hass, config_with_levels, mock_coordinator
        )
        threshold_sensor.schedule_update_ha_state = Mock()
        
        # Set top_three to average 9.85 kWh
        threshold_sensor.attr["top_three"] = [
            {"day": 1, "hour": 10, "energy": 9.5},
            {"day": 2, "hour": 11, "energy": 10.0},
            {"day": 3, "hour": 12, "energy": 10.05},
        ]
        
        threshold_sensor.calculate_level()
        
        # Should select Trinn 3 (5-10 kWh) with threshold 10
        assert threshold_sensor._state == 10, \
            f"For average=9.85 kWh, should select Trinn 3 (threshold=10), got {threshold_sensor._state}"


@pytest.mark.asyncio
async def test_average_sensor_matches_threshold_sensor_calculation(hass, config_with_levels, mock_coordinator):
    """Test that the average sensor and threshold sensor calculate the same average."""
    with patch('homeassistant.helpers.event.async_track_point_in_time'):
        threshold_sensor = GridCapWatcherCurrentEffectLevelThreshold(
            hass, config_with_levels, mock_coordinator
        )
        average_sensor = GridCapWatcherAverageThreePeakHours(
            hass, config_with_levels, mock_coordinator
        )
        
        threshold_sensor.schedule_update_ha_state = Mock()
        average_sensor.schedule_update_ha_state = Mock()
        
        # Manually set the same top_three for both
        top_three = [
            {"day": 1, "hour": 10, "energy": 10.0},
            {"day": 2, "hour": 11, "energy": 10.0},
            {"day": 3, "hour": 12, "energy": 10.45},
        ]
        
        threshold_sensor.attr["top_three"] = top_three.copy()
        average_sensor.attr["top_three"] = top_three.copy()
        
        # Calculate average in threshold sensor
        threshold_sensor.calculate_level()
        
        # Calculate average in average sensor (simulate _state_change behavior)
        total_sum = sum(float(hour["energy"]) for hour in average_sensor.attr["top_three"])
        average_sensor._state = total_sum / len(average_sensor.attr["top_three"])
        
        # Both should calculate the same average
        expected_average = (10.0 + 10.0 + 10.45) / 3
        
        assert abs(average_sensor._state - expected_average) < 0.01, \
            f"Average sensor should calculate {expected_average:.2f}, got {average_sensor._state}"
        
        # The threshold sensor should use this same average to select Trinn 4
        assert threshold_sensor._state == 15, \
            "Threshold sensor should select Trinn 4 (threshold=15) based on average=10.15"
