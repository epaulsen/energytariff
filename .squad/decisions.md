# Squad Decisions

## Active Decisions

### Bug B: Reference Assignment in _threshold_state_change (0.3.0)

**Author:** Geordi  
**Date:** 2026-03  
**Status:** CONFIRMED — Bug B is now numerically demonstrated  
**Decision:** Apply shallow copy fix to eliminate data loss

---

**Summary:** Bug B (`_threshold_state_change` reference assignment in 0.3.0) is confirmed as a real, 
observable data-loss defect at the January→February month boundary. The test harness `--month-boundary` 
flag reproduces it deterministically for all 4 synthetic sensors.

---

**Before/After: 0.2.6 vs 0.3.0 (sensor_1_power)**

January top-3:
| Rank | Date/Time | Watts |
|---|---|---|
| 1 | 2026-01-03 17:00 UTC | 10,228.8 W |
| 2 | 2026-01-14 18:00 UTC | 9,679.0 W |
| 3 | 2026-01-08 18:00 UTC | 9,502.8 W |

avg_sensor.top_three AFTER threshold monthly reset:
| Version | Result |
|---|---|
| **0.2.6** | `[Jan 8 18:00, Jan 14 18:00, Jan 3 17:00]` (all peaks intact) ✓ SAFE |
| **0.3.0** | `[]` (wiped — Bug B triggered) ✗ DATA LOSS |

---

**Mechanism:** In 0.3.0, `_threshold_state_change` assigns a direct reference:
```python
self.attr["top_three"] = threshold_data.top_three  # Points to same list object
```

When threshold resets (`self.attr["top_three"] = []`), avg_sensor's peaks are silently discarded 
because both reference the same list.

---

**Fix:** Replace with shallow copy:
```python
self.attr["top_three"] = list(threshold_data.top_three)
```

---

**Evidence:** `logfiles/results_026_boundary.txt`, `logfiles/results_030_boundary.txt`

### Issue #34 Regressions Fixed — Three Fixes Applied

**Author:** Geordi (fixes), Worf (tests), Spock (review)  
**Date:** 2026-03  
**Status:** APPROVED — PR #39 MERGED, RELEASE SHIPPED

---

**Summary:** Three regressions affecting the "Average peak hour energy" sensor in 0.3.0 have been 
identified, tested, fixed, and shipped via PR #39.

---

**Fix 1 — Regression A (P0): Avg Sensor Stale When Exceeding GRID_LEVELS**

**File:** `custom_components/energytariff/sensor.py`  
**Class:** `GridCapWatcherAverageThreePeakHours`  
**Method:** `_state_change`  
**Change:** Removed the short-circuit guard `if self._levels is not None: return None`

Avg sensor now always calls `calculate_top_three` from effectstate regardless of GRID_LEVELS config, 
restoring 0.2.6 behavior. When consumption exceeds all configured levels, `get_level()` returns None 
and `thresholddata.on_next()` never fires; without the short-circuit, the avg sensor tracks peaks 
independently.

---

**Fix 2 — Regression B (P0): Reference Sharing in _threshold_state_change**

**File:** `custom_components/energytariff/sensor.py`  
**Class:** `GridCapWatcherAverageThreePeakHours`  
**Method:** `_threshold_state_change`  
**Change:** `self.attr["top_three"] = threshold_data.top_three` → 
`self.attr["top_three"] = list(threshold_data.top_three)`

Both sensors were sharing the same mutable list object. When threshold resets its list to `[]`, 
avg sensor's peaks were silently discarded. Shallow copy creates independent list object.

---

**Fix 3 — Bug A (P1): Month Field Missing in calculate_top_three**

**File:** `custom_components/energytariff/utils.py`  
**Function:** `calculate_top_three`  
**Changes:**
- Added `"month": localtime.month` to each entry dict
- Updated collision deduction check to use `(month, day)` instead of `day` alone
- Backward-compat: entries missing `month` treated as current-month during computation

**File:** `custom_components/energytariff/sensor.py`  
**Classes:** `GridCapWatcherCurrentEffectLevelThreshold`, `GridCapWatcherAverageThreePeakHours`  
**Method:** `async_added_to_hass` (both classes)  
**Changes:** On restore, entries without `month` or with wrong month discarded. Valid entries 
include `month` in restored dict.

---

**Test Suite:**
- 3 regression tests written by Worf: `test_regression_a`, `test_regression_b`, `test_bug_a`
- 26 total tests passing after fixes
- All tests fail on unfixed 0.3.0; all pass on 0.2.6; all pass on fixed 0.3.0

---

**PR:** #39 — https://github.com/epaulsen/energytariff/pull/39  
**Branch:** fix/issue-34-avg-sensor-stale  
**Commit SHA:** 708e22d71acc2568c415043fdb95c4438888d324  
**Review:** Spock APPROVED  
**Status:** MERGED, RELEASE SHIPPED

---

### Issue #22: Jinja2 Templates for LEVEL_PRICE

**Authors:** Spock (plan), Geordi (impl + fix), Worf (tests)  
**Date:** 2026-03  
**Status:** APPROVED — READY FOR MERGE

---

**Summary:** `LEVEL_PRICE` now accepts Jinja2 templates (e.g., `{{ states('sensor.electricity_price') }}`) in addition to static numbers. Users can automate price-level changes via HA sensors or `input_number` entities without editing YAML.

---

**Implementation Details**

**Schema change:**
```python
vol.Required(LEVEL_PRICE): vol.Any(cv.Number, cv.template)
```
`cv.Number` first ensures backward compatibility: numeric inputs stay as floats.

**Init pre-processing:**
`cv.template` converts raw YAML strings to `Template` objects before `__init__` runs. Pre-processing binds `hass` to each:
```python
if isinstance(price_raw, template_helper.Template):
    price_raw.hass = hass
```

**Runtime resolution:**
Inside synchronous `calculate_level()` `@callback`:
```python
if isinstance(price_value, template_helper.Template):
    resolved_price = float(price_value.render(parse_result=True))
else:
    resolved_price = float(price_value)
```
Template rendering errors (TemplateError, ValueError) are caught; update is skipped and error logged; state not corrupted.

---

**Backward Compatibility**

| Scenario | Before | After | Result |
|---|---|---|---|
| `price: 135` (int) | Works | cv.Number matches, float(135) | ✅ Identical |
| `price: 135.5` (float) | Works | cv.Number matches, float(135.5) | ✅ Identical |
| `price: "{{ states('sensor.x') }}"` | Error | Template validated, rendered at runtime | ✅ New feature |
| Template error | N/A | Logged, level skipped | ✅ Graceful |

---

**Files Changed**

- `custom_components/energytariff/sensor.py` — schema, init pre-processing, calculate_level()
- `tests/test_sensor.py` — 6 new tests (regression + happy path + error paths)
- `README.md` — documentation with 4 YAML examples

---

**Test Results**

- 32/32 tests passing (26 prior + 6 new)
- Key tests: static regression, template happy path, entity unavailable, non-numeric render, schema accept/reject

---

**Review History**

1. Spock (analysis): APPROVED concept
2. Geordi (implementation): 32 tests pass
3. Worf (tests): All 6 tests pass
4. Spock (review 1): **REJECTED** — found dead code (`isinstance(str)` never fires)
5. Geordi (fix): Surgical change — `isinstance(str)` → `isinstance(Template)`, assign hass
6. Spock (final): **APPROVED** after fix

---

**Key Pattern**

`cv.template` is a voluptuous validator that **converts** raw YAML strings to Template objects before `__init__` runs. Always use `isinstance(x, template_helper.Template)` to detect templates (never check for `str`), and assign `.hass` to bind the HA instance — do not reconstruct.

---

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
