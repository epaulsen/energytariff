# Decision: Regression Tests Written for Issue #34

**Author:** Worf  
**Date:** 2026-03  
**Status:** COMPLETE — all 3 tests written, verified correct  

---

## Summary

Three regression tests have been added to `tests/test_sensor.py` to permanently guard
against the three confirmed defects in 0.3.0 (Regression A, Regression B, Bug A).

All tests PASS on the current fixed codebase. Each was verified to FAIL when its
corresponding fix is reverted, confirming the tests are pinning the right behaviour.

---

## Tests Written

### 1. `test_regression_a_exceeds_all_levels`

**Regression:** When `GRID_LEVELS` is configured and consumption exceeds ALL configured
thresholds, `get_level()` returns `None`, `thresholddata` is never broadcast, and the
`_state_change` short-circuit meant the avg sensor was never updated.

**Assertion:** After feeding 3 days of energy data (7.0 kWh — above the 5.0 max level),
`avg_sensor.attr["top_three"]` must have 3 entries and `avg_sensor._state` must not be None.

**Fails if:** `if self._levels is not None: return None` is re-added to `_state_change` of
`GridCapWatcherAverageThreePeakHours`.

---

### 2. `test_regression_b_reference_not_copy`

**Regression:** `_threshold_state_change` did `self.attr["top_three"] = threshold_data.top_three`
(reference assignment). Both sensors shared the same mutable list. In-place mutation of
the originating list silently affected the avg sensor's data.

**Assertion:** After broadcasting a `GridThresholdData` with a 3-entry `source_list`, then
calling `source_list.clear()`, the avg sensor's `top_three` must still contain 3 entries.

**Fails if:** `list(threshold_data.top_three)` is reverted to `threshold_data.top_three`.

---

### 3. `test_bug_a_month_collision_in_calculate_top_three`

**Bug:** `calculate_top_three` stored only `day` (1–31), not `month`. If the monthly reset
was missed, a January day-5 entry would shadow a February day-5 entry (same day number →
same slot). The February reading was silently ignored or overwritten.

**Assertion:** After feeding a January day-5 entry (5.0 kWh), then feeding a February day-5
entry (2.0 kWh) into the same top_three (simulating a missed reset), at least one entry
must have `month == 2` and `day == 5`.

**Fails if:** `month` field and month-aware collision detection are removed from
`calculate_top_three` in `utils.py`.

---

## Full Test Suite Status

```
26 passed in 0.16s
```

No existing tests broken.

---

## Important Finding: Fixes Were Already Applied

When I examined the codebase to write *failing* tests, I found that Geordi had already
committed all three fixes prior to this task being assigned. The fix commits are:

- `956f4a0` — Regression A + B fixes in `sensor.py`
- Related commit — Bug A fix (`month` field) in `utils.py`

The regression tests I wrote now serve as permanent guards. They would fail if anyone
reverts these fixes in future PRs.
