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

### Issue #22 — Templating in LEVEL_PRICE (2025-07)

**How LEVEL_PRICE flows at runtime:**

1. `LEVEL_SCHEMA` validates config at load time. `LEVEL_PRICE` is stored raw (int/float) in `_levels`.
2. `GridCapWatcherCurrentEffectLevelThreshold.__init__` stores `self._levels = config.get(GRID_LEVELS)` — a list of dicts.
3. On every energy state change, `_state_change` → `calculate_level()` → `get_level()` picks the matching level dict.
4. `calculate_level()` at line 405 does `float(found_threshold["price"])` — direct cast, no indirection.
5. The float is wrapped in `GridThresholdData` and broadcast via `self._coordinator.thresholddata.on_next(...)`.
6. `GridCapacityWatcherCurrentLevelPrice._threshold_state_change` receives it as `state.price` and sets sensor state.

**Key architectural insight:** `calculate_level()` is a synchronous method called from a synchronous `@callback`. Template resolution must use `Template.render()` (sync), not `async_render()`. Template objects should be pre-built at init time (not on every update cycle) to avoid repeated construction overhead.

**Safe template pre-processing pattern:**
```python
# In __init__, after self._levels = config.get(GRID_LEVELS):
if self._levels:
    for level in self._levels:
        if isinstance(level[LEVEL_PRICE], str):
            level[LEVEL_PRICE] = template_helper.Template(level[LEVEL_PRICE], hass)
```

**No other sensors need changes** — `GridCapacityWatcherCurrentLevelName`, `GridCapacityWatcherCurrentLevelPrice`, and `GridCapWatcherAverageThreePeakHours` all receive `price` as a pre-resolved float via `GridThresholdData`. The resolution point is singular: `calculate_level()` in `GridCapWatcherCurrentEffectLevelThreshold`.

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

---

## Issue #22 Review — Template Support for LEVEL_PRICE (2025-07)

**Status:** REJECTED — returned to Geordi for one targeted fix

**What was correct:**
- Schema: `vol.Any(cv.Number, cv.template)` — correct order, backward compatible
- Imports: `template_helper` and `TemplateError` at module level ✓
- `calculate_level()`: uses `Template.render(parse_result=True)` (sync, correct for `@callback`); catches `TemplateError` + `ValueError`; does not broadcast on failure ✓
- No `min=0` added (negatives preserved) ✓
- `LEVEL_THRESHOLD` untouched ✓
- 32/32 tests pass ✓

**The defect:**

`__init__` pre-processing checks `isinstance(price_raw, str)` — but `cv.template` in the schema already converts the raw YAML string to a `Template(hass=None)` before `__init__` runs. Verified: `cv.template("{{ ... }}")` returns a Template with `hass=None`, not a str. The `isinstance(price_raw, str)` check is dead code; Template objects loaded from real YAML configs will have `hass=None` and fail when `render()` tries to access HA state.

**Fix required (Geordi):**
```python
if isinstance(price_raw, template_helper.Template):
    price_raw.hass = hass
```
Also add one test that passes a template string through the schema into `__init__` and asserts `price.hass is hass`.

**Tests miss this** because all 6 Issue #22 tests inject mock Templates directly into `_levels` *after* construction — bypassing the `__init__` path entirely.

**Verdict file:** `.squad/decisions/inbox/spock-issue-22-review.md`

---

## top_three Upgrade Wipe Analysis (2025-07)

**Issue:** After upgrading from "0.3.1" to current main, `top_three` on avg sensor was empty.

**Root cause:** `_restore_top_three()` (sensor.py lines 115–117) discards entries where `item_month is None`. Pre-PR-#39 code (0.3.0 and the code-identical "0.3.1" HACS release) saves top_three entries without a `month` field. All saved history is silently discarded on first restart after upgrade.

**Key facts:**
- `0.3.0 calculate_top_three` entries: `{"day", "hour", "energy"}` — no `month`
- `_restore_top_three`: `if item_month is None: continue` → discards all legacy entries
- **Inconsistency:** `calculate_top_three` treats no-month entries as current-month (lenient), but `_restore_top_three` discards them (strict)
- Bug B (reference assignment) is **confirmed fixed** at line 555: `list(threshold_data.top_three)` ✓
- PR #40 introduced **no regression** — the refactor extracted identical logic

**Fix:** Change `_restore_top_three` to use `int(item.get("month", current_month))` instead of `None` default — matches `calculate_top_three` leniency, preserves data on upgrade.

**Findings:** `.squad/decisions/inbox/spock-topthree-regression.md`

---

## Issue #22 Final Approval — Template Support for LEVEL_PRICE (2025-07)

**Status:** APPROVED — all criteria met

**Fix verified:**
- `isinstance(price_raw, template_helper.Template)` at line 341: correctly targets Template objects produced by `cv.template` schema validation — not dead code
- `price_raw.hass = hass` at line 342: binds hass to template at init time so `render()` can access HA state at runtime
- `calculate_level()` at line 408–419: sync `render(parse_result=True)`, catches `TemplateError`/`ValueError`, returns False on failure — no corrupt broadcast
- No unintended changes: `LEVEL_THRESHOLD` untouched, schema order `vol.Any(cv.Number, cv.template)` preserved, no `min=0` added

**Test result:** 32/32 passed (6 new Issue #22 tests + 26 prior regression tests)

**Verdict file:** `.squad/decisions/inbox/spock-issue-22-final.md`

---

## _restore_top_three Migration Fix Review (2026-03)

**Date:** 2026-03  
**Status:** APPROVED

**What was reviewed:**
- `_restore_top_three()` in `sensor.py`: `item.get("month", None)` → `item.get("month", current_month)`, `is None` branch removed
- 4 new tests under `# --- Upgrade migration: _restore_top_three ---`

**Findings:**
- Fix is correct: `current_month` is in scope at the `.get()` call (line 114 → line 116), default correctly matches `calculate_top_three` leniency
- Prior-month filtering unchanged and verified
- Malformed-month edge case is theoretical only; same risk existed before fix, no change warranted
- All 4 tests are sound; Bug B guard is meaningful and cross-chains both fixes
- 36/36 tests pass

**Verdict file:** `.squad/decisions/inbox/spock-topthree-review.md`
