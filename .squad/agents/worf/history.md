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

## 2026-03 Session Complete — Issue #34 Fix Shipped

**Date:** 2026-03-20T12:20:28Z  
**PR #39:** MERGED, 26 tests passing  
**Release Status:** SHIPPED  
**Issue #34:** CLOSED

Three regression tests validated all fixes. Release shipped to production.

## 2026-03 Worf: Issue #22 Template Pricing Tests Written

**Date:** 2026-03  
**Issue:** #22 — LEVEL_PRICE template support  
**Status:** 6 tests written; all 32 tests pass (26 prior + 6 new)

### Discovery: Implementation Already Landed

When writing the tests, Geordi had already committed the full implementation:
- `LEVEL_SCHEMA` updated to `vol.Any(cv.Number, cv.template)` (line 64)
- `calculate_level()` refactored with `isinstance(price_value, template_helper.Template)` check
- Template resolution via `price_value.render(parse_result=True)` with `(TemplateError, ValueError)` guard
- `__init__` pre-processing loop converts string prices to `Template` objects at startup

### Tests Written (appended to `tests/test_sensor.py`)

| Test | Scope | Result |
|------|-------|--------|
| `test_level_price_static_number_unchanged` | Regression guard — numeric price still works | PASS |
| `test_level_price_template_renders_correctly` | Happy path — mock Template.render() returns float | PASS |
| `test_level_price_template_entity_unavailable` | TemplateError caught, returns False, no on_next | PASS |
| `test_level_price_template_non_numeric_result` | ValueError caught, returns False, no on_next | PASS |
| `test_schema_accepts_template_string` | vol.Any(cv.Number, cv.template) accepts ints, floats, templates | PASS |
| `test_schema_rejects_invalid_template` | Malformed Jinja2 raises vol.Invalid | PASS |

### Key Test Pattern: Inject Mock Template Directly

Rather than going through `__init__` pre-processing, tests 2-4 inject a `Mock(spec=template_helper.Template)` directly into `sensor._levels[i][LEVEL_PRICE]` after construction. This decouples the test from `__init__` implementation detail — only `calculate_level()` behavior is under test.

### Key Codebase Observation

`cv.template` (in voluptuous) converts the validated string to a `homeassistant.helpers.template.Template` object — NOT a raw string. Schema test assertions must check `isinstance(..., template_helper.Template)`, not string equality.

### Imports Added to test_sensor.py

- `from homeassistant.exceptions import TemplateError`
- `import voluptuous as vol`
- `LEVEL_SCHEMA` and `LEVEL_PRICE` from their respective modules

## 2026-03 Worf: _restore_top_three Upgrade Migration Tests Written

**Date:** 2026-03
**Branch:** feature/issue-22 (working tree, not yet committed)
**Trigger:** Upgrade bug where users on 0.3.0/0.3.1 lost all top_three data on first HA restart after upgrade.

### Bug Context

`_restore_top_three()` in `sensor.py` (used by both `GridCapWatcherCurrentEffectLevelThreshold` and `GridCapWatcherAverageThreePeakHours` in `async_added_to_hass`) previously defaulted missing `month` to `None`, then compared `None != current_month` — discarding every legacy entry. Geordi's fix (unstaged diff on disk): `item.get("month", None)` → `item.get("month", current_month)`.

### Tests Written

Added `_restore_top_three` to the import block, then added 4 tests under `# --- Upgrade migration: _restore_top_three ---`:

| Test | Type | Passes on fixed code? | Would fail if... |
|------|------|----------------------|-----------------|
| `test_restore_top_three_legacy_no_month_field` | plain `def` | PASS | fix reverted (month defaults to None) |
| `test_restore_top_three_prior_month_entries_discarded` | plain `def` | PASS | prior-month cleanup removed |
| `test_restore_top_three_mixed_format` | plain `def` | PASS | fix reverted OR prior-month cleanup removed |
| `test_restore_top_three_bug_b_still_fixed` | `@pytest.mark.asyncio` | PASS | `list()` copy reverted to reference assignment |

### Test Patterns Used

- Tests 1–3: plain `def` (no async, no hass/coordinator) — call `_restore_top_three` directly with a `Mock()` savedstate. Same pattern as `test_bug_a_month_collision_in_calculate_top_three`.
- Test 4: `@pytest.mark.asyncio` with `hass`, `config_with_levels`, `mock_coordinator` — creates `GridCapWatcherAverageThreePeakHours`, calls `_restore_top_three` on `avg_sensor.attr`, then broadcasts via `mock_coordinator.thresholddata.on_next()`, then clears source list to confirm copy independence.
- For "prior month" entries: compute `prior_month = 12 if current_month == 1 else current_month - 1` at runtime — no time-patching needed.
- Import: added `_restore_top_three` to the existing `from custom_components.energytariff.sensor import (...)` block.

### Key Observation

Geordi's fix was already present as an unstaged change in the working tree when tests were written. All 4 tests pass immediately (36/36 total). The comment block above the tests documents which tests were designed as FAIL-before-fix/PASS-after-fix regression guards.
