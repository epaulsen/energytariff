# Geordi — Project Knowledge

## Project Context
- **Project:** energytariff — HomeAssistant custom integration for energy tariff monitoring
- **Tech stack:** Python, HomeAssistant custom component framework
- **Code location:** `custom_components/energytariff/`
- **Tests:** `tests/` using pytest with HA test utilities
- **User:** Erling Paulsen

## Core Context
- Run tests with: `pytest tests/test_sensor.py -v`
- All tests must pass before submitting changes
- New functionality requires new tests
- HA developer docs: https://developers.home-assistant.io/

## Learnings

### 2026-01 CSV Analysis & Synthetic Data Generation

**Source files analysed (logfiles/):**
- `history.csv` — sensor_1: ~10s intervals, high heating load (mean 5065W, max 11812W). Large house.
- `history_epaulsen.csv` — sensor_2: exactly 10s intervals, moderate household (mean 2314W, max 6884W).
- `history_hm.csv` — sensor_3: ~11–12s irregular intervals, moderate (mean 2649W, max 8129W).
- `history_ms.csv` — sensor_4: MIXED — hourly for first ~100 rows (Jan 1–4), then switches to ~2s
  high-resolution from Jan 5 onwards. Wide range 402–12250W (mean 2526W).

**Norwegian household power patterns confirmed:**
- Night floor never zero — persistent winter heating baseline (~50% of mean)
- Morning peak 06:00–08:00 UTC (07:00–09:00 CET): 25–30% above daily mean
- Evening peak 16:00–20:00 UTC (17:00–21:00 CET): 35–40% above daily mean — dominant peak
- Weekends ~10% higher than weekdays (people at home)

**Synthetic generation approach:**
- AR(1) smoothing (α=0.15) on top of tod × weekday × peak-day multipliers to prevent abrupt jumps
- Each sensor has different peak_days (3–5 per month) to give varied top-3 monthly peak candidates
- sensor_4 generated at ~2s intervals matching dominant source pattern (1.34M rows for January)
- Script: `logfiles/generate_synthetic.py`

**Output row counts:** sensor_1: 267,826 | sensor_2: 267,835 | sensor_3: 235,026 | sensor_4: 1,339,189

---

## 2026-03 Cross-Agent Integration

### Issue #34 Context (from Spock Analysis)

The synthetic CSV data aligns directly with issue #34 regression testing needs:

**Spock identified two root causes in "Average peak hour energy" sensor (energytariff 0.3.0):**

1. **Bug A: Month boundary validation missing** — `calculate_top_three` uses only `day` (1–31), no month field. If monthly reset is missed, November data persists into December, causing cross-month pollution and "appears to use last 30 days" user reports. Fix: Add `month` field; validate on restore.

2. **Bug B: Reference assignment in threshold broadcast** — `_threshold_state_change` does `self.attr["top_three"] = threshold_data.top_three` (direct reference, not copy). Both sensors share the same list; if one resets, the other has stale reference. Explains post-upgrade instability. Fix: Use `list(threshold_data.top_three)` for shallow copy.

**Test Strategy:**
- Use `sensor_*_january.csv` synthetic data for month-long top-3 peak extraction testing
- Peak days seeded into each sensor (varied per sensor) allow realistic test scenarios
- Validate that Bug A fixes prevent cross-month pollution across month boundaries
- Validate that Bug B fixes maintain independent state during threshold broadcasts

**Next:** Regression test suite using Geordi's CSV data once Spock's fixes are implemented.

---

### 0.2.6 vs 0.3.0 Regression Test — Findings

**Harness:** `logfiles/test_harness.py` (not committed, gitignored)  
**Results:** `logfiles/results_026.txt`, `logfiles/results_030.txt`  
**Full findings:** `.squad/decisions/inbox/geordi-026-vs-030-findings.md`

**Key learnings:**

1. **`calculate_top_three` is identical in both 0.2.6 and 0.3.0.** Single-month cold-start computation gives byte-identical results for all 4 sensors. No logic regression in the core algorithm.

2. **The real regression in 0.3.0 is Bug B** — `_threshold_state_change` on `GridCapWatcherAverageThreePeakHours` does:
   ```python
   self.attr["top_three"] = threshold_data.top_three  # direct reference
   ```
   This method **does not exist in 0.2.6**. After monthly reset on the threshold sensor, the average sensor's reference becomes stale. Demonstrated live via `--simulate-bug-b` flag.

3. **Bug A (no month field) predates both versions** — same code in both, only manifests on HA restart near month boundary, not observable from single-month harness alone.

4. **API inspection pattern**: The harness detects these patterns via static text search of sensor.py at each version path, providing a fast structural diff without importing HA.

5. **Top-three peaks confirmed** for January 2026 synthetic data:
   - sensor_1: Jan 3 17:00 (10,228.8 W) → Jan 14 18:00 → Jan 8 18:00
   - sensor_2: Jan 17 17:00 (4,780.3 W) → Jan 11 17:00 → Jan 25 19:00
   - sensor_3: Jan 2 17:00 (4,986.5 W) → Jan 9 18:00 → Jan 23 17:00
   - sensor_4: Jan 13 17:00 (4,740.5 W) → Jan 27 17:00 → Jan 6 17:00

---

### Bug B Reproduced at Jan→Feb Boundary

**Harness extension:** `--month-boundary` flag added to `logfiles/test_harness.py`  
**Results:** `logfiles/results_026_boundary.txt`, `logfiles/results_030_boundary.txt`

**What was implemented:**
- `detect_bug_b(version_path)` — scans sensor.py for the `self.attr["top_three"] = threshold_data.top_three` pattern
- `generate_february_data()` — 48h of synthetic Feb 2026 data (~2500 W, ±300 W, `random.gauss` seeded)
- `simulate_month_boundary()` — models the critical path through January → reset → February for both versions
- `print_boundary_results()` / `run_month_boundary_mode()` — outputs per the specified format

**Key simulation logic:**
- **0.2.6 model:** avg sensor computes top_three independently each hour. Threshold broadcast after reset only updates `grid_threshold_level` (not top_three). After threshold resets + broadcasts: avg still holds January peaks.
- **0.3.0 Bug B model:** avg sensor's top_three IS threshold's top_three via reference assignment. Threshold resets to new `[]`, then broadcasts with that empty list. avg._threshold_state_change fires → `avg.attr["top_three"] = []` — January peaks wiped.

**Confirmed numeric results (all 4 sensors):**

| | 0.2.6 | 0.3.0 |
|---|---|---|
| avg_sensor after threshold reset | ✓ January peaks intact | ✗ [] (WIPED) |
| Bug B triggered | NO | YES ⚠️ |
| January peaks preserved | YES | NO |

Example (sensor_1_power):
- Jan top-3: Jan 3 17:00 (10228.8 W), Jan 14 18:00 (9679.0 W), Jan 8 18:00 (9502.8 W)
- 0.2.6 after reset: avg_sensor still shows all three (safe)
- 0.3.0 after reset: avg_sensor = [] (data loss)
