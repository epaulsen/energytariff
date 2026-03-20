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
