# Worf — Project Knowledge

## Project Context
- **Project:** energytariff — HomeAssistant custom integration for energy tariff monitoring
- **Tech stack:** Python, HomeAssistant custom component framework
- **Code location:** `custom_components/energytariff/`
- **Tests:** `tests/test_sensor.py` (primary test file)
- **User:** Erling Paulsen

## Core Context
- Run tests with: `pytest tests/test_sensor.py -v`
- All tests must pass before PRs are submitted
- Adding or changing functionality requires adding tests
- HA test utilities: https://developers.home-assistant.io/docs/development_testing

## Learnings

---

## 2026-03 Scribe Final Integration

### Revised Issue #34 Context — Test Authoring Guidance

**Status:** Spock's revised analysis merged; team decisions updated. Ready for test implementation.

### Regressions Identified

1. **Regression A (P0 — Silent Data Loss):**
   - Avg sensor's `_state_change` short-circuits when GRID_LEVELS configured
   - Relies entirely on threshold sensor broadcasts via `thresholddata.on_next()`
   - If consumption exceeds all levels, `get_level()` returns None, broadcast never fires
   - Avg sensor goes stale (never receives updates)
   - In 0.2.6: avg sensor independently calculated top_three on every update (no dependency)
   - **User symptoms:** Values jump after restart, appear unstable

2. **Regression B (P0 — Code Fragility):**
   - `_threshold_state_change` does reference assignment: `self.attr["top_three"] = threshold_data.top_three`
   - Both sensors share same mutable list object
   - When threshold resets, avg sensor retains stale reference
   - On post-upgrade restart: two sensors' states diverge, then get overwritten immediately
   - **User symptoms:** Post-upgrade instability, sudden data changes

3. **Bug A (P1 — Pre-existing):**
   - No `month` field in top_three entries; uses only day number (1–31)
   - If monthly reset missed, prior-month entries persist
   - Day-number collision causes old entries to shadow new ones or overwrite them
   - **User symptoms:** Wrong days vs grid operator (e.g., showing Jan 5 instead of Feb 5)

### Test Authoring Requirements

**Test Suite Strategy:**
- Use Geordi's synthetic CSV data (`logfiles/sensor_*_january.csv`) for all tests
- Peak days are seeded (varied per sensor) for reproducible scenarios
- Boundary tests confirm Bug A and Regression B at month transitions

**Test Cases to Write:**

| Test | Scenario | Assertion |
|------|----------|-----------|
| **regression_a_exceeds_levels** | GRID_LEVELS max = 5.0 kW, 3 days with peaks > 5.0 kW (avg 7.0 kW) | avg_sensor top_three STALE (empty or no update) while threshold_sensor is updated |
| **regression_b_reference_copy** | GRID_LEVELS configured, trigger threshold reset mid-month | avg_sensor should have independent copy, NOT stale reference |
| **regression_b_restore_divergence** | Restore avg_sensor and threshold_sensor with different top_three, then first AMS read | Both sensors maintain their restored state OR are synchronized via shallow copy (NOT mixed) |
| **bug_a_month_collision** | Jan 5 entry in top_three, then Feb 5 energy reading arrives | Feb 5 should be independent entry (not shadow/overwrite Jan 5 even if lower energy) |
| **regression_a_stale_then_drop** | GRID_LEVELS max = 5.0 kW, 3 days > 5.0 kW (stale), then day 4 = 3.0 kW | avg_sensor JUMPS from stale to new value with all 4 days data (explains "up and down" symptom) |

**Regression Baseline:**
- Synthetic data top-3 confirmed identical in 0.2.6 and 0.3.0 (`logfiles/results_026.txt` vs `results_030.txt`)
- Test harness with `--month-boundary` flag confirms Regression B at Jan→Feb boundary
- All tests should pass on 0.2.6 and FAIL on 0.3.0 (before fixes), then PASS after Geordi's fixes

### Implementation Order

1. **Write tests for Regression A + B** (P0 — blocking release)
2. **Write tests for Bug A** (P1 — high-impact but less urgent)
3. Validate all tests **fail on 0.3.0 without fixes**, **pass on 0.2.6**
4. After Geordi implements fixes: all tests **pass on fixed 0.3.0**

**Status:** Ready to author; waiting for fix implementation to validate test suite.

---

## 2026-03 Worf: Regression Tests Written (Issue #34)

### Discovery: Fixes Already Applied

When I went to write the failing regression tests, I discovered that Geordi had **already committed all three fixes** before the squad was formally tasked with this work:

- `956f4a0` — Removed `_state_change` short-circuit in avg sensor; added `thresholddata` subscription → **Regression A fixed**
- Same commit — Changed reference assignment to `list(threshold_data.top_three)` → **Regression B fixed**  
- `calculate_top_three` in `utils.py` — Added `month` field + (month, day) collision detection → **Bug A fixed**

### Tests Written

Three regression tests added to `tests/test_sensor.py`. All **PASS** on the current fixed code and **FAIL** when fixes are reverted (confirmed by reversion testing).

| Test | File | Status on fixed code | Would fail if... |
|------|------|----------------------|-----------------|
| `test_regression_a_exceeds_all_levels` | test_sensor.py | PASS | `_state_change` short-circuit re-added |
| `test_regression_b_reference_not_copy` | test_sensor.py | PASS | `list()` copy replaced by reference assignment |
| `test_bug_a_month_collision_in_calculate_top_three` | test_sensor.py | PASS | `month` field removed from `calculate_top_three` |

### Test Patterns Used

- `@pytest.mark.asyncio` with `hass` + `mock_coordinator` fixtures for sensor integration tests
- Create both `GridCapWatcherCurrentEffectLevelThreshold` and `GridCapWatcherAverageThreePeakHours` with the same coordinator to test the full reactive subscription chain
- `sensor.schedule_update_ha_state = Mock()` to suppress HA state update calls
- `mock_coordinator.effectstate.on_next(EnergyData(...))` to inject data through the whole pipeline
- `mock_coordinator.thresholddata.on_next(GridThresholdData(...))` to inject directly into avg sensor's threshold subscription
- For Bug A: call `calculate_top_three` directly (no HA infrastructure needed) — a plain `def` test (no asyncio)
- Reversion testing: temporarily patch source, run pytest in subprocess, restore — confirms test is pinning the right behaviour

### Key Codebase Observations

- `GridCapacityCoordinator` uses RxPY `BehaviorSubject` — replays last value to new subscribers; initial value is `None`
- Both sensors guard against `None` inputs at start of callbacks
- `calculate_top_three` mutates its input list in-place AND returns it (same object) — important for reference/copy reasoning
- BehaviorSubject subscription order matters: threshold_sensor and avg_sensor both subscribe to `effectstate`; both callbacks fire on every `on_next()`
- `venv` path: `.venv/bin/python -m pytest tests/test_sensor.py -v`

