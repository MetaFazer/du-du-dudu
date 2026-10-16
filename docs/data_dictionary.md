# Data Dictionary

_Last updated: Phase 1_

All tables live in the public schema of the PostgreSQL database. Every ETL write is idempotent.

---

## events

| Column | Type | Description |
|---|---|---|
| `event_id` | SERIAL PK | Surrogate key |
| `season` | INTEGER | Championship year (e.g. 2025) |
| `round` | INTEGER | Round number within the season (1-indexed) |
| `name` | TEXT | Race name (e.g. "Bahrain Grand Prix") |
| `circuit` | TEXT | Circuit name (e.g. "Bahrain International Circuit") |
| `country` | TEXT | Country (e.g. "Bahrain") |
| `date` | DATE | Race date (Sunday) |

Unique constraint: `(season, round)`.

---

## sessions

| Column | Type | Description |
|---|---|---|
| `session_id` | SERIAL PK | Surrogate key |
| `event_id` | INTEGER FK → events | Parent event |
| `type` | TEXT | Session type: `Q`, `R`, `Sprint`, `SQ` |

Unique constraint: `(event_id, type)`.

---

## drivers

| Column | Type | Description |
|---|---|---|
| `driver_id` | SERIAL PK | Surrogate key |
| `code` | CHAR(3) | Three-letter driver code (e.g. `VER`) |
| `full_name` | TEXT | Full name (e.g. "Max Verstappen") |
| `number` | INTEGER | Permanent race number |

---

## teams

| Column | Type | Description |
|---|---|---|
| `team_id` | SERIAL PK | Surrogate key |
| `name` | TEXT | Constructor name as returned by Jolpica |
| `color_hex` | CHAR(7) | Brand color (`#rrggbb`) — sourced from team branding, not official |

---

## entries

| Column | Type | Description |
|---|---|---|
| `season` | INTEGER | Championship year |
| `driver_id` | INTEGER FK → drivers | Driver |
| `team_id` | INTEGER FK → teams | Team this driver raced for in this season |

Primary key: `(season, driver_id)`.

---

## results

| Column | Type | Description |
|---|---|---|
| `result_id` | SERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `driver_id` | INTEGER FK → drivers | Driver |
| `grid` | INTEGER | Starting grid position (NULL for qualifying/sprint qualifying) |
| `position` | INTEGER | Finishing position (NULL for DNF/DNS/DSQ) |
| `status` | TEXT | Result status from Jolpica (e.g. "Finished", "+1 Lap", "Engine") |
| `points` | NUMERIC(6,2) | Points scored in this session |

---

## laps

Core fact table. One row per driver per lap in a session.

| Column | Type | Description |
|---|---|---|
| `lap_id` | BIGSERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `driver_id` | INTEGER FK → drivers | Driver |
| `lap_no` | SMALLINT | Lap number within the session |
| `lap_time_ms` | INTEGER | Lap duration in milliseconds (NULL if unavailable) |
| `s1_ms` | INTEGER | Sector 1 time in milliseconds |
| `s2_ms` | INTEGER | Sector 2 time in milliseconds |
| `s3_ms` | INTEGER | Sector 3 time in milliseconds |
| `compound` | TEXT | Tyre compound: `SOFT`, `MEDIUM`, `HARD`, `INTERMEDIATE`, `WET`, `UNKNOWN` |
| `tyre_life` | SMALLINT | Number of laps this tyre set has been used |
| `stint` | SMALLINT | Stint number (1-indexed, inferred by FastF1) |
| `pit_in_time` | BIGINT | Time of pit entry in ms from session start (NULL = not an in-lap) |
| `pit_out_time` | BIGINT | Time of pit exit in ms from session start (NULL = not an out-lap) |
| `track_status` | TEXT | FastF1 track status string (e.g. `"1"` = green, `"4"` = VSC) |
| `position` | SMALLINT | Track position at end of lap |
| `is_accurate` | BOOLEAN | FastF1 `IsAccurate` flag — False means timing data is unreliable |
| `is_clean` | BOOLEAN | Derived clean-lap flag (see methodology.md §2) |

Unique constraint: `(session_id, driver_id, lap_no)`.

---

## pit_stops

| Column | Type | Description |
|---|---|---|
| `pit_stop_id` | SERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `driver_id` | INTEGER FK → drivers | Driver |
| `stop_no` | SMALLINT | Stop number within the race (1-indexed) |
| `lap` | SMALLINT | Lap on which the car entered the pit lane |
| `pit_lane_time_ms` | INTEGER | Total pit lane time in milliseconds (PitOutTime − PitInTime). NULL if either value is unavailable. **Source: FastF1 laps data.** |

---

## race_control

| Column | Type | Description |
|---|---|---|
| `rc_id` | BIGSERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `time` | BIGINT | Message time in ms from session start |
| `lap` | SMALLINT | Lap number the message relates to (NULL if not lap-specific) |
| `category` | TEXT | Message category (e.g. `Flag`, `SafetyCar`, `DRS`) |
| `flag` | TEXT | Flag status (e.g. `GREEN`, `YELLOW`, `RED`, `SC`, `VSC`) |
| `message` | TEXT | Full message text |

---

## weather

| Column | Type | Description |
|---|---|---|
| `weather_id` | BIGSERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `time` | BIGINT | Sample time in ms from session start |
| `air_temp` | NUMERIC(5,2) | Air temperature in °C |
| `track_temp` | NUMERIC(5,2) | Track surface temperature in °C |
| `rainfall` | BOOLEAN | Whether rainfall is detected at this time |

---

## telemetry_lap

One row per **10 m grid point** per lap. Only stored for the fastest lap of each driver per session.

| Column | Type | Description |
|---|---|---|
| `telem_id` | BIGSERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `driver_id` | INTEGER FK → drivers | Driver |
| `lap_no` | SMALLINT | Lap number |
| `dist_m` | NUMERIC(8,2) | Distance from lap start in metres (10 m grid) |
| `speed` | NUMERIC(6,2) | Speed in km/h |
| `throttle` | NUMERIC(5,2) | Throttle position 0–100 % |
| `brake` | BOOLEAN | Brake pedal on/off (not pressure) |
| `gear` | SMALLINT | Gear selected |
| `rpm` | INTEGER | Engine RPM |
| `drs` | SMALLINT | DRS channel integer (FastF1 raw value) |
| `x` | NUMERIC(12,4) | Map X coordinate (FastF1 circuit reference frame) |
| `y` | NUMERIC(12,4) | Map Y coordinate |

_(Populated in Phase 4.)_

---

## corners

| Column | Type | Description |
|---|---|---|
| `corner_id` | SERIAL PK | Surrogate key |
| `circuit` | TEXT | Circuit name (matches `events.circuit`) |
| `corner_no` | SMALLINT | Corner number (from FastF1 circuit info, 1-indexed) |
| `dist_m` | NUMERIC(8,2) | Distance from lap start in metres |
| `x` | NUMERIC(12,4) | Map X coordinate |
| `y` | NUMERIC(12,4) | Map Y coordinate |

_(Populated in Phase 4.)_

---

## corner_stats

Derived per-lap, per-corner statistics from telemetry. All values are **estimated** from on/off brake data and interpolated telemetry.

| Column | Type | Description |
|---|---|---|
| `cs_id` | BIGSERIAL PK | Surrogate key |
| `session_id` | INTEGER FK → sessions | Session |
| `driver_id` | INTEGER FK → drivers | Driver |
| `lap_no` | SMALLINT | Lap number |
| `corner_no` | SMALLINT | Corner number |
| `brake_point_m` | NUMERIC(8,2) | Distance (m) where brake channel first turns on before the corner |
| `min_speed` | NUMERIC(6,2) | Lowest speed (km/h) within the corner window |
| `throttle_pickup_m` | NUMERIC(8,2) | Distance (m) where throttle first exceeds threshold after apex |
| `exit_speed` | NUMERIC(6,2) | Speed (km/h) at the end of the corner window |

**Note**: brake data is on/off boolean — never infer braking force or pressure.

_(Populated in Phase 4.)_

---

## dq_log

Audit log for all data quality checks.

| Column | Type | Description |
|---|---|---|
| `log_id` | BIGSERIAL PK | Surrogate key |
| `run_id` | TEXT | UUID identifying the ETL run |
| `table_name` | TEXT | Table the check applies to |
| `check_name` | TEXT | Name of the specific check |
| `severity` | TEXT | `INFO`, `WARNING`, or `ERROR` |
| `row_count` | INTEGER | Number of affected rows (NULL for session-level failures) |
| `detail` | TEXT | Human-readable description of the issue |
| `created_at` | TIMESTAMPTZ | When the check was recorded (UTC) |
