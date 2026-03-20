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

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
