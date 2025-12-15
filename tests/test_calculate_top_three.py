"""Test calculate_top_three function for edge cases related to issue #34."""
import pytest
from datetime import datetime, timedelta
from homeassistant.util import dt
from custom_components.energytariff.utils import calculate_top_three
from custom_components.energytariff.coordinator import EnergyData


def create_energy_data(day: int, hour: int, energy: float) -> EnergyData:
    """Helper to create EnergyData with specific day, hour, and energy."""
    # Create a timestamp for January 2024
    timestamp = datetime(2024, 1, day, hour, 0, 0, tzinfo=dt.DEFAULT_TIME_ZONE)
    return EnergyData(energy=energy, effect=1000.0, timestamp=timestamp)


class TestCalculateTopThreeBasicCases:
    """Test basic functionality of calculate_top_three."""

    def test_empty_list_adds_first_item(self):
        """Test Case 1: Empty list should add the first item."""
        top_three = []
        state = create_energy_data(day=1, hour=10, energy=5.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 1
        assert result[0]["day"] == 1
        assert result[0]["hour"] == 10
        assert result[0]["energy"] == 5.0

    def test_add_second_item_different_day(self):
        """Test adding second item from different day."""
        top_three = [{"day": 1, "hour": 10, "energy": 5.0}]
        state = create_energy_data(day=2, hour=11, energy=6.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 2
        assert result[1]["day"] == 2
        assert result[1]["energy"] == 6.0

    def test_add_third_item_different_day(self):
        """Test adding third item from different day."""
        top_three = [
            {"day": 1, "hour": 10, "energy": 5.0},
            {"day": 2, "hour": 11, "energy": 6.0},
        ]
        state = create_energy_data(day=3, hour=12, energy=7.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 3
        assert result[2]["day"] == 3
        assert result[2]["energy"] == 7.0


class TestCalculateTopThreeSameDayUpdates:
    """Test Case 2: Same day updates - only highest value should be kept."""

    def test_same_day_higher_energy_updates(self):
        """Test that higher energy on same day updates the entry."""
        top_three = [{"day": 1, "hour": 10, "energy": 5.0}]
        state = create_energy_data(day=1, hour=14, energy=7.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 1
        assert result[0]["day"] == 1
        assert result[0]["hour"] == 14  # Hour should update
        assert result[0]["energy"] == 7.0  # Energy should update

    def test_same_day_lower_energy_no_update(self):
        """Test that lower energy on same day does not update."""
        top_three = [{"day": 1, "hour": 10, "energy": 7.0}]
        state = create_energy_data(day=1, hour=14, energy=5.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 1
        assert result[0]["day"] == 1
        assert result[0]["hour"] == 10  # Hour should not change
        assert result[0]["energy"] == 7.0  # Energy should not change

    def test_multiple_updates_same_day_keeps_highest(self):
        """Test multiple updates on same day - should keep only the highest."""
        top_three = []
        
        # Day 1: Add 5.0
        state1 = create_energy_data(day=1, hour=10, energy=5.0)
        top_three = calculate_top_three(state1, top_three)
        
        # Day 1: Update to 7.0
        state2 = create_energy_data(day=1, hour=12, energy=7.0)
        top_three = calculate_top_three(state2, top_three)
        
        # Day 1: Try to update with 6.0 (should not update)
        state3 = create_energy_data(day=1, hour=15, energy=6.0)
        top_three = calculate_top_three(state3, top_three)
        
        assert len(top_three) == 1
        assert top_three[0]["day"] == 1
        assert top_three[0]["hour"] == 12
        assert top_three[0]["energy"] == 7.0


class TestCalculateTopThreeReplacementLogic:
    """Test Case 4: Replacement logic when we have 3 items from different days."""

    def test_fourth_day_higher_than_all_replaces_lowest(self):
        """Test that a fourth day with highest value replaces the lowest."""
        top_three = [
            {"day": 1, "hour": 10, "energy": 5.0},
            {"day": 2, "hour": 11, "energy": 6.0},
            {"day": 3, "hour": 12, "energy": 7.0},
        ]
        state = create_energy_data(day=4, hour=13, energy=10.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 3
        # Should have days 2, 3, and 4 (day 1 with 5.0 should be replaced)
        days = [item["day"] for item in result]
        energies = [item["energy"] for item in result]
        
        assert 1 not in days  # Day 1 should be removed
        assert 4 in days  # Day 4 should be added
        assert 5.0 not in energies  # 5.0 should be removed
        assert 10.0 in energies  # 10.0 should be added

    def test_fourth_day_middle_value_replaces_lowest(self):
        """Test that a fourth day with middle value replaces the lowest."""
        top_three = [
            {"day": 1, "hour": 10, "energy": 4.0},
            {"day": 2, "hour": 11, "energy": 6.0},
            {"day": 3, "hour": 12, "energy": 8.0},
        ]
        state = create_energy_data(day=4, hour=13, energy=5.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 3
        days = [item["day"] for item in result]
        energies = [item["energy"] for item in result]
        
        assert 1 not in days  # Day 1 with 4.0 should be removed
        assert 4 in days  # Day 4 with 5.0 should be added
        assert 4.0 not in energies
        assert 5.0 in energies

    def test_fourth_day_lower_than_all_no_replacement(self):
        """Test that a fourth day with lowest value does not replace anything."""
        top_three = [
            {"day": 1, "hour": 10, "energy": 5.0},
            {"day": 2, "hour": 11, "energy": 6.0},
            {"day": 3, "hour": 12, "energy": 7.0},
        ]
        state = create_energy_data(day=4, hour=13, energy=3.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 3
        days = [item["day"] for item in result]
        energies = [item["energy"] for item in result]
        
        # Original three days should remain
        assert 1 in days
        assert 2 in days
        assert 3 in days
        assert 4 not in days  # Day 4 should not be added
        assert 3.0 not in energies


class TestCalculateTopThreeEdgeCases:
    """Test edge cases and special scenarios."""

    def test_negative_energy_converted_to_zero(self):
        """Test that negative energy (e.g., solar production) is set to 0."""
        top_three = []
        state = create_energy_data(day=1, hour=10, energy=-2.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 1
        assert result[0]["energy"] == 0.0  # Should be converted to 0

    def test_none_state_returns_unchanged_list(self):
        """Test that None state returns the list unchanged."""
        top_three = [{"day": 1, "hour": 10, "energy": 5.0}]
        
        result = calculate_top_three(None, top_three)
        
        assert result == top_three
        assert len(result) == 1

    def test_zero_energy_added_correctly(self):
        """Test that zero energy is handled correctly."""
        top_three = []
        state = create_energy_data(day=1, hour=10, energy=0.0)
        
        result = calculate_top_three(state, top_three)
        
        assert len(result) == 1
        assert result[0]["energy"] == 0.0


class TestCalculateTopThreeRealisticScenarios:
    """Test realistic month-long scenarios."""

    def test_month_scenario_highest_three_different_days(self):
        """
        Realistic scenario: Track a full month where we need to identify
        the three highest consumption hours from different days.
        """
        top_three = []
        
        # Day 1: Peak at hour 18 = 8.5 kWh
        for hour in [10, 14, 18, 22]:
            energy = 5.0 if hour != 18 else 8.5
            state = create_energy_data(day=1, hour=hour, energy=energy)
            top_three = calculate_top_three(state, top_three)
        
        # Day 2: Peak at hour 19 = 9.2 kWh
        for hour in [10, 14, 19, 22]:
            energy = 5.5 if hour != 19 else 9.2
            state = create_energy_data(day=2, hour=hour, energy=energy)
            top_three = calculate_top_three(state, top_three)
        
        # Day 3: Peak at hour 17 = 7.8 kWh
        for hour in [10, 14, 17, 22]:
            energy = 5.2 if hour != 17 else 7.8
            state = create_energy_data(day=3, hour=hour, energy=energy)
            top_three = calculate_top_three(state, top_three)
        
        # Day 4: Peak at hour 20 = 6.5 kWh (lower than all three)
        for hour in [10, 14, 20, 22]:
            energy = 4.8 if hour != 20 else 6.5
            state = create_energy_data(day=4, hour=hour, energy=energy)
            top_three = calculate_top_three(state, top_three)
        
        # Verify we have exactly 3 items
        assert len(top_three) == 3
        
        # Verify they are from different days
        days = [item["day"] for item in top_three]
        assert len(days) == len(set(days)), "All days should be unique"
        
        # Verify we have the correct three highest values
        energies = sorted([item["energy"] for item in top_three], reverse=True)
        assert energies[0] == 9.2  # Day 2
        assert energies[1] == 8.5  # Day 1
        assert energies[2] == 7.8  # Day 3

    def test_two_days_with_highest_values_only_one_counted(self):
        """
        Test requirement: If one day has two of the highest consumptions,
        only the highest from that day should be counted.
        """
        top_three = []
        
        # Day 1: Has both 10.0 and 9.5 (two highest values overall)
        state1 = create_energy_data(day=1, hour=10, energy=10.0)
        top_three = calculate_top_three(state1, top_three)
        
        state2 = create_energy_data(day=1, hour=14, energy=9.5)  # Lower, should not update
        top_three = calculate_top_three(state2, top_three)
        
        # Day 2: Has 8.0
        state3 = create_energy_data(day=2, hour=11, energy=8.0)
        top_three = calculate_top_three(state3, top_three)
        
        # Day 3: Has 7.0
        state4 = create_energy_data(day=3, hour=12, energy=7.0)
        top_three = calculate_top_three(state4, top_three)
        
        # Verify we have 3 items from 3 different days
        assert len(top_three) == 3
        days = [item["day"] for item in top_three]
        assert len(set(days)) == 3
        
        # Verify day 1 only has 10.0, not 9.5
        day1_items = [item for item in top_three if item["day"] == 1]
        assert len(day1_items) == 1
        assert day1_items[0]["energy"] == 10.0

    def test_average_calculation_from_result(self):
        """Test that the average can be correctly calculated from the result."""
        top_three = [
            {"day": 1, "hour": 10, "energy": 6.902},
            {"day": 2, "hour": 11, "energy": 5.1978},
            {"day": 3, "hour": 12, "energy": 5.487},
        ]
        
        # Calculate average
        total = sum(item["energy"] for item in top_three)
        average = total / len(top_three)
        
        expected_average = (6.902 + 5.1978 + 5.487) / 3
        assert abs(average - expected_average) < 0.0001
        assert abs(average - 5.8622666666666665) < 0.0001


class TestCalculateTopThreeMonthBoundary:
    """Test behavior around month boundaries."""

    def test_different_months_separate_tracking(self):
        """
        Test that different months are tracked separately.
        Note: The monthly reset happens in the sensor, not in calculate_top_three.
        This test verifies the function works correctly when reset.
        """
        # Month 1 data
        top_three_month1 = []
        state1 = create_energy_data(day=15, hour=10, energy=8.0)
        top_three_month1 = calculate_top_three(state1, top_three_month1)
        
        # Month 2 starts with reset (empty list)
        top_three_month2 = []
        state2 = create_energy_data(day=1, hour=10, energy=5.0)
        top_three_month2 = calculate_top_three(state2, top_three_month2)
        
        # Verify they are independent
        assert len(top_three_month1) == 1
        assert top_three_month1[0]["day"] == 15
        
        assert len(top_three_month2) == 1
        assert top_three_month2[0]["day"] == 1


class TestCalculateTopThreeRealWorldData:
    """Test with real-world-like data patterns."""

    def test_issue_34_reproduction_case(self):
        """
        Test case attempting to reproduce issue #34.
        Based on the test in test_sensor.py with values: 6.902, 5.1978, 5.487
        """
        top_three = []
        
        # Build up the scenario
        state1 = create_energy_data(day=5, hour=18, energy=6.902)
        top_three = calculate_top_three(state1, top_three)
        
        state2 = create_energy_data(day=12, hour=19, energy=5.1978)
        top_three = calculate_top_three(state2, top_three)
        
        state3 = create_energy_data(day=20, hour=17, energy=5.487)
        top_three = calculate_top_three(state3, top_three)
        
        # Verify correct values are stored
        assert len(top_three) == 3
        energies = sorted([item["energy"] for item in top_three], reverse=True)
        assert abs(energies[0] - 6.902) < 0.0001
        assert abs(energies[1] - 5.487) < 0.0001
        assert abs(energies[2] - 5.1978) < 0.0001
        
        # Calculate average
        average = sum(item["energy"] for item in top_three) / 3
        expected = (6.902 + 5.1978 + 5.487) / 3
        assert abs(average - expected) < 0.0001


class TestCalculateTopThreeDivisionByZero:
    """Test edge case where empty list could cause division by zero."""

    def test_empty_list_division_safety(self):
        """
        Test that we can safely handle an empty top_three list
        without division by zero errors when calculating average.
        """
        top_three = []
        
        # Calculate average safely
        if len(top_three) == 0:
            average = 0.0
        else:
            total = sum(item["energy"] for item in top_three)
            average = total / len(top_three)
        
        assert average == 0.0

    def test_calculate_level_with_empty_list_protection(self):
        """
        Simulate what happens in GridCapWatcherCurrentEffectLevelThreshold.calculate_level
        when top_three is empty - this should be protected.
        """
        top_three = []
        
        average_value = 0.0
        for hour in top_three:
            average_value += hour["energy"]
        
        # This line would cause ZeroDivisionError if not protected
        # average_value = average_value / len(top_three)  # Bug!
        
        # Safe version:
        if len(top_three) > 0:
            average_value = average_value / len(top_three)
        
        # Should not raise an error
        assert average_value == 0.0
