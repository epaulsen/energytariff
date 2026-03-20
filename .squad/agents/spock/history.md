# Spock — Project Knowledge

## Project Context
- **Project:** energytariff — HomeAssistant custom integration for energy tariff monitoring
- **Tech stack:** Python, HomeAssistant custom component framework
- **Code location:** `custom_components/energytariff/`
- **Tests:** `tests/` using pytest with HA test utilities
- **User:** Erling Paulsen

## Core Context
- Run tests with: `pytest tests/test_sensor.py -v`
- All tests must pass before PRs are submitted
- New functionality requires new tests

## Learnings

### Issue #34 — "Average peak hour energy" regression in 0.3.0 (2025-07)

**Two root causes identified:**

**Bug A (all users, pre-existing):** `calculate_top_three` stores only `day` (1–31), not `month`. If HA misses the monthly reset (integration down at month boundary), prior-month entries persist and corrupt new-month calculations. Day numbers from the old month collide with current-month days. Fix: add `month` field to each top_three entry; validate on restore.

**Bug B (users with `GRID_LEVELS` configured, introduced in 0.3.0):** `_threshold_state_change` does `self.attr["top_three"] = threshold_data.top_three` — a direct reference assignment, not a copy. On first restart after upgrading from 0.2.x, the two sensors' independently-saved states diverge; the first threshold broadcast overwrites the average sensor's freshly-restored `top_three`. Also creates fragile reference sharing that breaks when either sensor's `_async_reset_meter` fires.

**Key code locations:**
- `utils.py: calculate_top_three` — missing month validation
- `sensor.py: GridCapWatcherAverageThreePeakHours._threshold_state_change` — reference overwrite
- `sensor.py: async_added_to_hass` (both sensors) — no month boundary check on restore

**Tests needed:** Unit test for `calculate_top_three` with cross-month data; restore integration test verifying `top_three` survives first threshold broadcast.

**Full analysis:** `.squad/decisions.md` (merged from inbox)

---

## 2026-03 Session Complete — Issue #34 Fix Shipped

**Date:** 2026-03-20T12:20:28Z  
**PR #39:** MERGED, all 26 tests passing  
**Release Status:** SHIPPED  
**Issue #34:** CLOSED

All three regressions fixed and deployed. Worf's test suite passed review. Release shipped to production.
