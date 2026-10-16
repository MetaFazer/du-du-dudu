# Methodology

_Last updated: Phase 1_

This document explains every ETL decision, cleaning rule, and analytical definition used in Du-Du-Du. Any metric shown in the app is either raw data or is labeled **"estimated"**.

---

## 1. Data Sources

| Source | Used for | API / Library |
|---|---|---|
| **FastF1** | Lap times, sector times, tyre data, stint info, pit in/out times, track status, race control messages, weather, car telemetry, position data, circuit geometry | Python `fastf1` library (wraps the F1 Live Timing API cache) |
| **Jolpica-F1** | Race calendar, driver standings, race results, qualifying results, pit stop durations (fallback only) | REST API at `https://api.jolpi.ca/ergast/f1/` — open, no auth required |

### FastF1 cache
FastF1 downloads session data from the F1 timing API and caches it locally (directory set via `FF1_CACHE_DIR` env var, default `./fastf1_cache`). The cache is gitignored. On a fresh machine, the first ETL run triggers a full download.

### Pit stop time source
**Primary source: FastF1** lap-level `PitInTime` and `PitOutTime`.  
- Both are `Timedelta` values measured from session start with **millisecond** precision.  
- Pit lane time = `PitOutTime (next lap) − PitInTime (current lap)`.  
- This is logged as the source in `dq_log` at ingestion time.

**Fallback: Jolpica** provides pit stop duration in **whole seconds**, which is insufficient for precise analysis. Jolpica fallback is not currently implemented; it remains available if FastF1 data is missing.

---

## 2. Lap Cleaning Rules

A lap is flagged `is_clean = TRUE` only if **all** of the following conditions hold. These rules are implemented in [`etl/clean.py`](../etl/clean.py) and tested in [`tests/test_clean.py`](../tests/test_clean.py).

| # | Rule | Rationale |
|---|---|---|
| 1 | `pit_in_time IS NULL` | Exclude in-laps — driver is slowing for the pit box |
| 2 | `pit_out_time IS NULL` | Exclude out-laps — cold tyres, slow acceleration |
| 3 | `lap_no > 1` | Lap 1 includes standing-start, potential incidents and crowded braking zones |
| 4 | Track status contains no SC/VSC/Red Flag code | Laps under yellow / SC / VSC / red flag are not representative pace |
| 5 | Compound not WET or INTERMEDIATE | Wet-weather laps are not comparable to slick-compound laps |
| 6 | `IsAccurate == True` (FastF1 flag) | FastF1 marks laps where timing data is unreliable as `IsAccurate = False` |
| 7 | `lap_time_ms IS NOT NULL` | Cannot analyse a lap with no time |

### Track status codes
FastF1 encodes track status per lap as a string. Codes that disqualify a lap:

| Code | Meaning |
|---|---|
| `2` | Yellow flag |
| `3` | Safety Car deployed |
| `4` | Virtual Safety Car (VSC) deployed |
| `5` | Red flag |
| `6` | VSC ending |
| `7` | Virtual Safety Car (Yellow) |

Status `1` (green flag) is the only code that allows a clean lap. If the status string contains any of the above codes (e.g. `"14"` would be caught because `'4'` appears in it), the lap is excluded.

### Implausible time guard
Before cleaning-flag assignment, any lap with `lap_time_ms < 60 000` or `> 600 000` (outside 1 min – 10 min) has its `is_accurate` flag forced to `False`. These bounds are intentionally conservative; physically no F1 lap is shorter than ~1 minute. This guard is a data sanity check, not a pace filter.

---

## 3. ETL Idempotency

All ETL writes are idempotent:
- **Events, drivers, teams, entries** use `ON CONFLICT … DO UPDATE` (upsert).
- **Results, laps, pit_stops, race_control, weather** use `DELETE WHERE session_id = :sid` followed by `INSERT … ON CONFLICT DO UPDATE`. This ensures a full re-run of a session produces identical data.

---

## 4. Data Quality Log (`dq_log`)

Every ETL run generates a `run_id` (UUID). The following checks are run per session and persisted to `dq_log`:

| Check name | Severity if triggered | What it detects |
|---|---|---|
| `null_lap_times` | WARNING | Laps with no lap time |
| `implausible_lap_times` | WARNING | Laps outside [60 s, 600 s] |
| `duplicate_stints` | WARNING | Non-monotonic stint numbers per driver |
| `missing_laps` | WARNING | Gaps in a driver's lap number sequence |
| `driver_number_mismatch` | ERROR | Driver codes in FastF1 not found in the drivers table |
| `session_load_failure` | ERROR | FastF1 raised an exception loading a session |

Severity levels: `INFO` (no issues), `WARNING` (data anomaly, load continues), `ERROR` (data missing or load failed).

---

## 5. Scope

- **Season**: 2025 only for now. All ETL functions accept a `season` parameter and never hardcode 2025.
- **Sessions**: Qualifying (`Q`), Race (`R`), Sprint (`Sprint`), Sprint Qualifying (`SQ`) where applicable.
- **Telemetry**: Phase 4 (not yet loaded).
- **Corners / corner_stats**: Phase 4.

---

## 6. Analysis Definitions

_(Full SQL implementations in `sql/analysis/`. Populated in Phase 2.)_

### 6.1 Clean-lap pace
Median and interquartile range of `lap_time_ms` across all `is_clean` laps per driver per race session.

### 6.2 Pit loss *(estimated)*
`(in-lap time + out-lap time) − 2 × driver's median clean lap time in that race`

This is an **estimate**. It includes tyre warm-up time and is affected by traffic. It is always labeled "estimated" in the UI.

### 6.3 Undercut success
For pairs of cars within a configurable gap (default 3 s) where one pits before the other, compare their positions after both have completed their stops. Pit cycles that overlap with SC/VSC periods are excluded.

### 6.4 Tyre degradation
Lap time vs `tyre_life` per compound per circuit, clean laps only. Fuel load effect is noted as an uncontrolled variable (fuel burn improves lap time monotonically over a stint; tyre deg works in the opposite direction).

### 6.5 Teammate gap
- **Qualifying**: Best-lap delta between teammates.
- **Race**: Median clean-lap difference at matched tyre age (same compound, ± N laps of tyre life), with a confidence interval reported.

### 6.6 Grid vs finish
Positions gained/lost = `finish_position − grid_position` per driver per race. DNFs excluded from the distribution, reported separately.

### 6.7 Reliability
DNF count by team and reason (mechanical vs accident, from Jolpica `status` field).

---

## 7. Telemetry pipeline

_(Phase 4. Documented here for completeness.)_

1. Per driver per qualifying/race session, take the **fastest lap** (by `lap_time_ms`).
2. Pull FastF1 car data (`sess.car_data`) and position data (`sess.pos_data`), add a distance channel, interpolate to a **fixed 10 m grid**.
3. **Delta time**: integrate time from speed over distance; scale each lap so its total equals the official lap time (reduces integration drift). Labeled "approximate" in the UI.
4. **Corners**: use FastF1 circuit info corners. Fallback: detect corners from curvature of smoothed x/y track map.
5. **Corner stats** windows (defaults, configurable):
   - Braking window: 150 m before corner entry to apex.
   - Throttle window: apex to 100 m after corner exit.
   - Brake data is on/off (boolean); never claim braking force or brake pressure.
6. **Mini-sectors**: 25 equal-distance segments; segment winner = lowest segment time.
