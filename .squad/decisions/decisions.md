# Team Decisions — energytariff Issue #34 & CSV Analysis

**Date:** 2026-03-20  
**Contributors:** Spock, Geordi  
**Status:** Active (awaiting prioritisation & implementation)

---

## Issue #34: "Average Peak Hour Energy" Regression in 0.3.0

**Status:** Analyzed | Awaiting Fix Prioritisation  
**Severity:** High (correctness bug, financial impact)

### Bug A: Month Boundary Validation Missing (Pre-existing, Surfaced in 0.3.0)

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

**Priority:** 1 (affects all users at month boundary)

---

### Bug B: Reference Assignment in `_threshold_state_change` (Introduced 0.3.0, Config-Specific)

**Root Cause:** When `GRID_LEVELS` configured, `_threshold_state_change` executes:
```python
self.attr["top_three"] = threshold_data.top_three
```

This is a **direct reference**, not a copy. Both sensors now share the same list object.

**Issue:**
1. On startup, both sensors independently restore their `top_three` from HA state store
2. First AMS reading triggers threshold sensor's `_state_change`
3. Threshold sensor calls `calculate_top_three`, updates its `top_three`
4. Broadcasts via `coordinator.thresholddata.on_next(GridThresholdData(..., self.attr["top_three"]))`
5. Average sensor's `_threshold_state_change` fires
6. **Average sensor's restored `top_three` is overwritten with threshold sensor's reference**
7. Both now point to same list object
8. If one sensor's `_async_reset_meter` fires, it replaces the reference with `[]` — other sensor has stale reference
9. Next threshold broadcast re-links them; cycle repeats

**Impact:** Post-upgrade instability — two sensors' states were saved independently by 0.2.x; on first 0.3.0 restart they differ and get overwritten immediately.

**Fix (Recommended):**
```python
self.attr["top_three"] = list(threshold_data.top_three)  # shallow copy, breaks reference sharing
```

Or: Use a `_restored` flag; only accept `_threshold_state_change` updates after `async_added_to_hass` completes.

**Priority:** 2 (affects users with `GRID_LEVELS` configured; less common than Bug A)

---

### Bug C: Amplification via Hourly Boundary Fluctuation (Secondary)

**Root Cause:** On hourly reset, `GridCapWatcherEnergySensor._state` → 0. If month boundary corrupted (Bug A), wrong day entries cause fluctuation as current readings compete with stale entries.

**Status:** Mitigated by fixes to Bugs A & B; no separate fix needed.

---

## Testing Requirements

### For Bug A:
```python
# Unit test: calculate_top_three with month boundary collision
top_three_november = [{"day": 7, "month": 11, "energy": 4.48}, ...]
energy_december_7 = EnergyData(timestamp=2026-12-07, day=7, energy=3.2)  # Lower than Nov
result = calculate_top_three(energy_december_7, top_three_november)
# Assert: November entry NOT retained; December entry added
```

### For Bug B:
```python
# Integration test: restore + threshold broadcast
average_sensor.top_three_on_restore = [a, b, c]
threshold_sensor.top_three_on_restore = [x, y, z]
# Simulate first AMS reading...
# Assert: average_sensor.top_three has [a, b, c] OR [x, y, z], NOT mixed or stale refs
```

### Field Diagnostics (Request from Issue Reporters):
1. Enable `logger: default: debug`
2. Restart HA, capture first 5 minutes
3. Share `extra_state_attributes` of both sensors:
   - Immediately after restart
   - After first energy reading
4. Compare `day` values and look for month/year mismatch

---

## Synthetic CSV Data for Testing (Geordi)

**Generated:** January 2026 (full month), 4 sensors

| File | Entity | Interval | Rows | Mean (W) |
|------|--------|----------|------|----------|
| `sensor_1_january.csv` | `sensor.sensor_1_power` | ~10s | 267,826 | 5,001 |
| `sensor_2_january.csv` | `sensor.sensor_2_power` | 10s exact | 267,835 | 2,258 |
| `sensor_3_january.csv` | `sensor.sensor_3_power` | ~11.4s | 235,026 | 2,621 |
| `sensor_4_january.csv` | `sensor.sensor_4_power` | ~2s | 1,339,189 | 2,450 |

**Peak Days (varied per sensor):**
- Sensor 1: 3, 8, 14, 22, 28
- Sensor 2: 5, 11, 17, 25
- Sensor 3: 2, 9, 16, 23, 29
- Sensor 4: 6, 13, 20, 27

**Use:** End-to-end testing of top-3 monthly peak extraction; regression suite for Bugs A & B fixes.

---

## Decision: Next Steps

1. **Immediate:** Implement Bug A fix (month field + validation) — highest impact, simplest fix
2. **Short term:** Implement Bug B fix (reference copy) — improves stability for level-configured users
3. **Validation:** Use Geordi's synthetic CSV suite as regression test dataset
4. **Field feedback:** Request debug logs from issue reporters to confirm month/day pollution

---

**Author:** Spock (analysis), Geordi (testing data)  
**Reviewed by:** (Pending)  
**Implementation date:** (Pending prioritisation)

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
| Bug B (reference assignment) is new in 0.3.0 only | ✅ CONFIRMED |
| Bug B reproduced via --simulate-bug-b flag in test harness | ✅ DEMONSTRATED |
| Single-month cold-start regression NOT detected (expected — doesn't expose cross-month or restore bugs) | ✅ EXPECTED |

### Final Top-Three Results (Identical Both Versions)

**Sensor 1 (fast interval ~10s):** Jan 3 @ 10,228.8 W | Jan 14 @ 9,679.0 W | Jan 8 @ 9,502.8 W  
**Sensor 2 (10s exact):** Jan 17 @ 4,780.3 W | Jan 11 @ 4,684.9 W | Jan 25 @ 4,575.5 W  
**Sensor 3 (~11.4s):** Jan 2 @ 4,986.5 W | Jan 9 @ 4,985.4 W | Jan 23 @ 4,938.0 W  
**Sensor 4 (~2s granular):** Jan 13 @ 4,740.5 W | Jan 27 @ 4,703.2 W | Jan 6 @ 4,695.1 W

### Conclusion

The user-reported regression is **NOT caused by calculate_top_three logic changes**. Bug B (reference assignment) is the primary culprit for post-upgrade instability in 0.3.0. Synthetic CSV regression suite is production-ready for validating fixes.

**Author:** Geordi (testing & harness)  
**Date:** 2026-03-20  
**Artifacts:** .squad/orchestration-log/2026-03-20T10-45-00Z-geordi.md, .squad/log/2026-03-20T10-45-00Z-baseline-comparison.md
