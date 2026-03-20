# Team Decisions — energytariff Issue #34 & CSV Analysis

**Date:** 2026-03-20  
**Contributors:** Spock, Geordi  
**Status:** Active (awaiting prioritisation & implementation)

---

## Issue #34: "Average Peak Hour Energy" Regression in 0.3.0

**Status:** REVISED ANALYSIS — Domain model corrected, regressions identified  
**Severity:** High (correctness bug, financial impact)  
**Contributors:** Spock (analysis), Geordi (testing)

---

## REVISED FINDINGS (2026-03-20)

### Critical Correction: Kapasitetsledd Domain Model

Norwegian grid tariffs include **kapasitetsledd** — a monthly capacity charge based on peak consumption:
- Grid operators measure the customer's **top-3 highest hourly average consumption readings per calendar month** (each from a DIFFERENT day)
- The **average of those 3 peaks** determines which capacity tier the customer pays
- The calculation **resets on the 1st of each month** — this is **correct and mandatory**

**Previous analysis error:** The initial Bug B finding labelled monthly reset as "data loss." This was WRONG. The monthly reset is intentional, domain-required functionality. This correction applies to all prior documentation.

**Source:** [Lyse — Hva er kapasitetsledd](https://www.lyse.no/kundeservice/artikler/22493920554513-hva-er-kapasitetsledd-og-hvordan-beregnes-kapasitetstrinn)

---

## REGRESSION A: Average Sensor Goes Stale (P0 — Silent Data Loss)

**Introduced in 0.3.0**

In 0.3.0, the average sensor's `_state_change` short-circuits when `GRID_LEVELS` is configured:
```python
def _state_change(self, state: EnergyData) -> None:
    if self._levels is not None:
        return None  # ← SKIPS all calculation
```

It relies entirely on `_threshold_state_change`, which fires when the threshold sensor broadcasts via `thresholddata.on_next()`. But that broadcast ONLY happens when `get_level()` finds a matching level:

```python
def calculate_level(self) -> bool:
    ...
    found_threshold = self.get_level(average_value)
    if found_threshold is not None:      # ← Only broadcasts if level found!
        self._coordinator.thresholddata.on_next(...)
```

**Silent failure:** If the user's average peak consumption exceeds ALL configured GRID_LEVELS thresholds, `get_level()` returns `None`, `thresholddata.on_next()` is never called, and the average sensor **never receives any updates**.

In 0.2.6: The average sensor independently calculated top_three from raw energy data on every update. It had no dependency on the threshold sensor.

**User symptom match:**
- **ojm88:** "values no longer match readings from grid operator" and "sensor values often change or are recalculated after restart" — average sensor goes stale during high-consumption periods, updates when consumption drops below configured levels, values appear to "jump"
- **erikaugl:** "Numbers going up and down daily" — avg sensor stale during high consumption, then updates when drops below threshold

**Fix (Recommended):** Move `thresholddata.on_next()` OUTSIDE the `if found_threshold is not None` guard in `calculate_level()`, OR remove the `_state_change` short-circuit so the average sensor always independently calculates.

**Priority:** P0

---

## REGRESSION B: Reference Assignment Fragility (P0 — Code Fragility)

**Introduced in 0.3.0**

```python
# _threshold_state_change
self.attr["top_three"] = threshold_data.top_three  # REFERENCE, not copy
```

`GridThresholdData.top_three` is the SAME list object as `GridCapWatcherCurrentEffectLevelThreshold.attr["top_three"]`. After this assignment, both sensors share one mutable list.

**Consequences:**
1. When `calculate_top_three` mutates the list (sorts in-place, appends, replaces entries), the average sensor's `extra_state_attributes` changes **without** `schedule_update_ha_state` being called. HA may persist an intermediate state.
2. Each sensor's `_async_reset_meter` does `self.attr["top_three"] = []`, creating a NEW list and breaking the reference link. This is safe because both resets fire back-to-back at the same scheduled time (creation-order guarantee from `async_track_point_in_time`). But if either sensor is reloaded independently (e.g., config reload), the other retains a stale reference.

On post-upgrade restart: Two sensors' states were saved independently by 0.2.x; on first 0.3.0 restart they differ and get overwritten immediately via reference sharing.

**Fix (Recommended):** Change to `self.attr["top_three"] = list(threshold_data.top_three)` — a shallow copy that preserves independence.

**Priority:** P0

---

## BUG A: Month Boundary Validation Missing (Pre-existing, Surfaced in 0.3.0)

**Root Cause:** `calculate_top_three` uses only `day` (1–31) for matching; no month or year stored.

**Scenario:**
1. HA shuts down Nov 30 or integration not running at midnight Dec 1
2. `_async_reset_meter` callback never fires (misses month boundary)
3. HA restarts Dec 2; restores November's `top_three`
4. December entries with colliding day numbers are compared against stale November values
5. November entry retained if December reading is lower; creates cross-month pollution

**Impact:** "Values appear to use last 30 days not current month" — exactly matches user reports.

**Fix (Recommended):**
- Add `month` field to each entry
- Update `calculate_top_three` to match on both month AND day
- On restore in `async_added_to_hass`, filter out entries with mismatched month or check `saved_state.attributes.get("month")` against `dt.now().month`

**Priority:** P1 (affects all users at month boundary)

---

## Complete Regressions & Bugs Summary

| Issue | Type | Priority | Root Cause | Fix |
|-------|------|----------|-----------|-----|
| **Regression A** | 0.3.0 | P0 | avg sensor short-circuits when GRID_LEVELS configured; stale if consumption exceeds all levels | Move `on_next()` outside guard OR remove short-circuit |
| **Regression B** | 0.3.0 | P0 | reference assignment shares mutable list between sensors | Use `list(threshold_data.top_three)` shallow copy |
| **Bug A** | Pre-existing | P1 | no month field in top_three; cross-month pollution on missed reset | Add `month` field; validate on restore |

---

## User Symptom → Root Cause Mapping

| User | Symptom | Most Likely Cause |
|------|---------|-------------------|
| jgallis | "Values reset after upgrade, missing entry" | Restart triggered `calculate_top_three` with accumulated multi-hour energy (pre-existing), possibly combined with Regression A (stale sensor if levels exceeded) |
| msandvold | "Wrong days, wrong values vs grid provider" | Bug A — cross-month contamination (completely different days = old month peaks persisting) |
| ojm88 | "Values change after restart, unstable" | Regression A (stale avg sensor) + Regression B (reference sharing on restart) |
| erikaugl | "Numbers going up and down daily" | Regression A — avg sensor goes stale during high-consumption, then updates when below threshold |

---

## Testing Requirements

### Test 1: Regression A — `get_level()` returns None → average sensor stale

```
Setup: GRID_LEVELS with max threshold = 5.0 kW
Simulate: Three days with peak consumption of 6.0, 7.0, 8.0 kWh (avg = 7.0, exceeds all levels)
Assert: threshold sensor's top_three is updated but thresholddata.on_next is NOT called
Assert: average sensor's top_three is STALE (empty or outdated)
Compare: In 0.2.6 the average sensor independently tracked the correct peaks
```

### Test 2: Regression B — Reference sharing vs copy

```
Setup: GRID_LEVELS configured, mid-month with 3 peaks established
Step 1: Verify both sensors share same list object after first threshold broadcast
Step 2: Trigger threshold's _async_reset_meter
Step 3: Before average resets, trigger AMS update
Assert: average sensor's top_three should NOT contain old month data
Compare: With shallow copy fix, average sensor's data is independent
```

### Test 3: Bug A — Cross-month contamination

```
Setup: Populate top_three with Jan 5 (3.0), Jan 10 (2.5), Jan 15 (2.8)
Simulate: Monthly reset callback is SKIPPED (HA was down)
Simulate: Feb 5 arrives with energy 1.5
Assert: Feb 5's entry silently gets eaten by the Jan 5 day-match
Expected: Feb 5 should be independent from Jan 5
```

### Test 4: Regression A — consumption drops below threshold after stale period

```
Setup: GRID_LEVELS max = 5.0 kW
Step 1: Simulate 3 days with peaks > 5.0 kW → avg exceeds all levels
Step 2: Verify average sensor is stale (no update received)
Step 3: Simulate day 4 with peak = 3.0 kW → avg drops below 5.0 kW
Step 4: Verify average sensor NOW updates (with data from all 4 days, not just day 4)
Assert: average sensor jumps from stale value to new value → explains "up and down" symptom
```

---

## Recommended Fix Implementation Order

| Priority | Fix | Effort |
|----------|-----|--------|
| P0 | **Regression A:** Move `thresholddata.on_next()` OUTSIDE the `if found_threshold is not None` guard in `calculate_level()`, OR remove the `_state_change` short-circuit so the average sensor always independently calculates. | Small |
| P0 | **Regression B:** Change to `self.attr["top_three"] = list(threshold_data.top_three)` (shallow copy). | Trivial |
| P1 | **Bug A:** Add `month` field to top_three entries. Validate month on restore and on each `calculate_top_three` call. Discard entries from prior months. | Medium |

---

## Testing Strategy & Artifacts

**Synthetic CSV data ready:** `logfiles/sensor_*_january.csv` (Geordi) — 4 sensors × 744 hourly datapoints (January 2026 synthetic). Peak days seeded into each sensor for realistic regression validation.

**Baseline established:** `logfiles/test_harness.py` with results at `logfiles/results_026.txt` and `logfiles/results_030.txt` — demonstrates Regression B reproduced at Jan→Feb boundary.

---

## Previous Analysis Sections (Superseded)

The following sections from earlier analysis have been consolidated into the revised findings above. Kept for audit trail but superseded by corrected domain model and Regression A/B findings.

---

## Regression Baseline Test Results (Geordi, 2026-03-20)

**Status:** Baseline established | Testing framework ready  
**Verification Method:** Dual worktrees (v0.2.6 and v0.3.0), synthetic sensor CSV data, regression harness

### Test Execution

- **Setup:** Git worktrees at `/tmp/energytariff_026` (tag v0.2.6) and `/tmp/energytariff_030` (tag v0.3.0)
- **Data:** 4 sensors × 744 hourly datapoints (January 2026 synthetic)
- **Harness:** `logfiles/test_harness.py` (20 KB) — reusable regression framework
- **Results:** `logfiles/results_026.txt` and `logfiles/results_030.txt`

### Findings

| Finding | Status |
|---------|--------|
| calculate_top_three produces identical output at 0.2.6 and 0.3.0 (byte-for-byte) | ✅ VERIFIED |
| Bug A (missing month field) is pre-existing in both versions | ✅ CONFIRMED |
| Regression B (reference assignment) is new in 0.3.0 only | ✅ CONFIRMED |
| Regression B reproduced via --simulate-bug-b flag in test harness | ✅ DEMONSTRATED |
| Single-month cold-start regression NOT detected (expected — doesn't expose cross-month or restore bugs) | ✅ EXPECTED |

### Final Top-Three Results (Identical Both Versions)

**Sensor 1 (fast interval ~10s):** Jan 3 @ 10,228.8 W | Jan 14 @ 9,679.0 W | Jan 8 @ 9,502.8 W  
**Sensor 2 (10s exact):** Jan 17 @ 4,780.3 W | Jan 11 @ 4,684.9 W | Jan 25 @ 4,575.5 W  
**Sensor 3 (~11.4s):** Jan 2 @ 4,986.5 W | Jan 9 @ 4,985.4 W | Jan 23 @ 4,938.0 W  
**Sensor 4 (~2s granular):** Jan 13 @ 4,740.5 W | Jan 27 @ 4,703.2 W | Jan 6 @ 4,695.1 W

### Conclusion

The user-reported regression is **NOT caused by calculate_top_three logic changes**. Regression B (reference assignment) is the primary culprit for post-upgrade instability in 0.3.0. Synthetic CSV regression suite is production-ready for validating fixes.

**Author:** Geordi (testing & harness)  
**Date:** 2026-03-20  
**Artifacts:** .squad/orchestration-log/2026-03-20T10-45-00Z-geordi.md, .squad/log/2026-03-20T10-45-00Z-baseline-comparison.md

---

## Decision: Next Steps

1. **Immediate:** Implement Regression A fix (remove short-circuit OR move on_next outside guard)
2. **Immediate:** Implement Regression B fix (shallow copy)
3. **Short term:** Implement Bug A fix (month field + validation) — highest impact for user base
4. **Validation:** Use Geordi's synthetic CSV suite as regression test dataset
5. **Field feedback:** Request debug logs from issue reporters to confirm month/day pollution

---

**Contributors:** Spock (revised analysis), Geordi (testing data), Worf (test authoring)  
**Final Review:** (Pending implementation)  
**Implementation Readiness:** P0 fixes are trivial; ready to code
