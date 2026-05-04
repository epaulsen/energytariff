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

### fix/average-peak-drops — Startup race condition review (2026-06)

**Branch:** `fix/average-peak-drops` | **Commit:** `0575f67` | **Verdict:** APPROVED

**Fix reviewed:** Single `async_add_entities` call with threshold sensors placed before avg.

**Fix is correct.** BehaviorSubject `subscribe()` delivers the current value synchronously. When threshold initialises first and its effectstate replay fires → updates thresholddata. When avg later subscribes to thresholddata → BehaviorSubject replays threshold's up-to-date value. The no-GRID_LEVELS path is unaffected (avg never subscribes to thresholddata).

**Non-blocking notes recorded:**
1. Sequential `async_added_to_hass` ordering is not formally guaranteed by asyncio task scheduling — it is reliable in practice in HA's entity platform but relies on implicit behaviour. Comment in code explains this, which is sufficient.
2. `list(threshold_data.top_three)` is a shallow copy — dict objects are shared. `calculate_top_three` Case 2 mutates dicts in-place. Benign today because RxPY synchronous delivery means avg._threshold_state_change always runs before avg._state_change (threshold subscribes to effectstate first, so thresholddata fires within threshold._state_change before avg._state_change runs). A `copy.deepcopy` would be more defensive.
3. `test_regression_e` validates behaviour given correct subscription order but does not test that HA's runtime achieves that order. The structural ordering assertion lives in `test_async_setup_platform_with_levels`.

**33/33 tests pass.**

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
