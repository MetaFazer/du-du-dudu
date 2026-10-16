"""
etl/ingest.py – FastF1 + Jolpica-F1 ingestion for one session or season.

Design decisions
----------------
* Every load function is parameterised by `season` (int) – never hardcoded.
* Each function is idempotent: it uses ON CONFLICT DO UPDATE (upsert) or
  deletes existing rows for a session before re-inserting.
* FastF1 failures per session are caught, logged to dq_log, and skipped.
  The run never crashes on a single bad session.
* Pit lane time source: FastF1 laps (PitInTime / PitOutTime).
  Jolpica pit stop data is available as a fallback but its time resolution
  is coarser (seconds, not milliseconds).  The source is noted in dq_log.

Jolpica API base URL: https://api.jolpi.ca/ergast/f1/
  (open, no key required, rate-limited to ~4 req/s)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.clean import apply_clean_flag, flag_implausible_times
from etl.quality import (
    check_driver_number_mismatch,
    check_session_load_failure,
    new_run_id,
    run_all_lap_checks,
    write_dq_log,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastF1 cache setup
# ---------------------------------------------------------------------------

_FF1_CACHE_CONFIGURED = False


def _configure_ff1_cache() -> None:
    global _FF1_CACHE_CONFIGURED
    if _FF1_CACHE_CONFIGURED:
        return
    cache_dir = os.environ.get("FF1_CACHE_DIR", "./fastf1_cache")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(cache_dir)
    _FF1_CACHE_CONFIGURED = True
    log.info("FastF1 cache enabled at %s", cache_dir)


# ---------------------------------------------------------------------------
# Jolpica API helpers
# ---------------------------------------------------------------------------

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_JOLPICA_DELAY = 0.1  # seconds between requests


def _jolpica_get(path: str, params: dict | None = None) -> dict:
    """GET from Jolpica with simple rate-limit delay and error handling."""
    url = f"{JOLPICA_BASE}/{path}"
    time.sleep(_JOLPICA_DELAY)
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Dimension loaders
# ---------------------------------------------------------------------------


def load_events(season: int, engine: Engine, run_id: str) -> None:
    """
    Upsert the calendar (events table) for a given season from Jolpica.

    Uses ON CONFLICT (season, round) DO UPDATE so re-running is safe.
    """
    log.info("Loading events for season %d", season)
    data = _jolpica_get(f"{season}.json")
    races = data["MRData"]["RaceTable"]["Races"]

    rows = [
        {
            "season": season,
            "round": int(r["round"]),
            "name": r["raceName"],
            "circuit": r["Circuit"]["circuitName"],
            "country": r["Circuit"]["Location"]["country"],
            "date": r["date"],
        }
        for r in races
    ]

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO events (season, round, name, circuit, country, date)
                VALUES (:season, :round, :name, :circuit, :country, :date)
                ON CONFLICT (season, round) DO UPDATE SET
                    name    = EXCLUDED.name,
                    circuit = EXCLUDED.circuit,
                    country = EXCLUDED.country,
                    date    = EXCLUDED.date
                """
            ),
            rows,
        )
    log.info("Upserted %d events for season %d", len(rows), season)


def load_drivers_and_teams(season: int, engine: Engine, run_id: str) -> None:
    """
    Upsert drivers, teams, and season entries from Jolpica driver standings.

    Driver color_hex is not available from Jolpica; we hard-code the 2025
    team colors (sourced from team branding) and will allow override via a
    config file in Phase 2.
    """
    log.info("Loading drivers/teams for season %d", season)

    # Fetch driver standings (gives us the full grid)
    data = _jolpica_get(f"{season}/driverStandings.json")
    standings = data["MRData"]["StandingsTable"]["StandingsLists"]
    if not standings:
        log.warning("No driver standings found for season %d", season)
        return
    driver_list = standings[0]["DriverStandings"]

    # 2025 team colour mapping (best approximation from team branding)
    TEAM_COLORS: dict[str, str] = {
        "Red Bull":              "#3671c6",
        "Mercedes":              "#27f4d2",
        "Ferrari":               "#e8002d",
        "McLaren":               "#ff8000",
        "Aston Martin":          "#229971",
        "Alpine F1 Team":        "#0093cc",
        "Williams":              "#64c4ff",
        "Haas F1 Team":          "#b6babd",
        "RB F1 Team":            "#6692ff",
        "Kick Sauber":           "#52e252",
    }

    teams_seen: dict[str, int] = {}   # constructor_id -> team_id

    with engine.begin() as conn:
        for entry in driver_list:
            drv = entry["Driver"]
            ctor = entry["Constructors"][0]  # first team for this driver this season

            code = drv.get("code", drv["driverId"][:3].upper())
            number_str = drv.get("permanentNumber", "0")
            number = int(number_str) if number_str else 0

            # Upsert driver
            result = conn.execute(
                text(
                    """
                    INSERT INTO drivers (code, full_name, number)
                    VALUES (:code, :full_name, :number)
                    ON CONFLICT (code) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        number    = EXCLUDED.number
                    RETURNING driver_id
                    """
                ),
                {
                    "code": code,
                    "full_name": f"{drv['givenName']} {drv['familyName']}",
                    "number": number,
                },
            )
            driver_id = result.fetchone()[0]

            # Upsert team (only once per constructor per season load)
            ctor_name = ctor["name"]
            if ctor_name not in teams_seen:
                color = TEAM_COLORS.get(ctor_name, "#888888")
                res2 = conn.execute(
                    text(
                        """
                        INSERT INTO teams (name, color_hex)
                        VALUES (:name, :color_hex)
                        ON CONFLICT (name) DO UPDATE SET
                            color_hex = EXCLUDED.color_hex
                        RETURNING team_id
                        """
                    ),
                    {"name": ctor_name, "color_hex": color},
                )
                teams_seen[ctor_name] = res2.fetchone()[0]

            team_id = teams_seen[ctor_name]

            # Upsert entry
            conn.execute(
                text(
                    """
                    INSERT INTO entries (season, driver_id, team_id)
                    VALUES (:season, :driver_id, :team_id)
                    ON CONFLICT (season, driver_id) DO UPDATE SET
                        team_id = EXCLUDED.team_id
                    """
                ),
                {"season": season, "driver_id": driver_id, "team_id": team_id},
            )

    log.info("Upserted %d drivers for season %d", len(driver_list), season)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

SESSION_TYPES = {
    "Q": "Q",
    "Qualifying": "Q",
    "R": "R",
    "Race": "R",
    "Sprint": "Sprint",
    "Sprint Qualifying": "SQ",
    "SQ": "SQ",
}


def _get_or_create_session(event_id: int, session_type: str, engine: Engine) -> int:
    """Return existing session_id or insert and return new one."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT session_id FROM sessions WHERE event_id=:eid AND type=:t"
            ),
            {"eid": event_id, "t": session_type},
        ).fetchone()
        if row:
            return row[0]
        result = conn.execute(
            text(
                """
                INSERT INTO sessions (event_id, type) VALUES (:eid, :t)
                ON CONFLICT (event_id, type) DO UPDATE SET type = EXCLUDED.type
                RETURNING session_id
                """
            ),
            {"eid": event_id, "t": session_type},
        )
        return result.fetchone()[0]


def _get_event_id(season: int, round_no: int, engine: Engine) -> int | None:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT event_id FROM events WHERE season=:s AND round=:r"),
            {"s": season, "r": round_no},
        ).fetchone()
    return row[0] if row else None


def _get_driver_id_map(engine: Engine) -> dict[str, int]:
    """Return {driver_code: driver_id} from the drivers table."""
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT code, driver_id FROM drivers")).fetchall()
    return {r[0]: r[1] for r in rows}


_DRIVER_SLUG_CACHE: dict[str, int] = {}


def _get_driver_slug_map(season: int, engine: Engine) -> dict[str, int]:
    """Return {driver_slug: driver_id} mapping Jolpica driverId (e.g. 'max_verstappen') to DB driver_id."""
    global _DRIVER_SLUG_CACHE
    if _DRIVER_SLUG_CACHE:
        return _DRIVER_SLUG_CACHE

    code_map = _get_driver_id_map(engine)
    try:
        data = _jolpica_get(f"{season}/drivers.json", params={"limit": 100})
        drivers = data.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
        for d in drivers:
            code = d.get("code") or d["driverId"][:3].upper()
            if code in code_map:
                _DRIVER_SLUG_CACHE[d["driverId"]] = code_map[code]
    except Exception as exc:
        log.warning("Could not fetch Jolpica drivers for slug mapping: %s", exc)

    return _DRIVER_SLUG_CACHE


def _parse_time_ms(time_str: str | None) -> int | None:
    """Parse lap or pit duration string ('1:34.725', '23.724') into milliseconds."""
    if not time_str or not isinstance(time_str, str):
        return None
    time_str = time_str.strip()
    try:
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2:
                m, s = parts
                return int((int(m) * 60 + float(s)) * 1000)
            elif len(parts) == 3:
                h, m, s = parts
                return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
        return int(float(time_str) * 1000)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Results loader
# ---------------------------------------------------------------------------


def load_results(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
) -> None:
    """Upsert race/qualifying results from Jolpica."""
    log.info("Loading results: season=%d round=%d type=%s", season, round_no, session_type)

    event_id = _get_event_id(season, round_no, engine)
    if event_id is None:
        log.warning("Event not found for season=%d round=%d – run load_events first", season, round_no)
        return

    session_id = _get_or_create_session(event_id, session_type, engine)
    driver_map = _get_driver_id_map(engine)

    # Jolpica endpoint differs by session type
    if session_type == "R":
        path = f"{season}/{round_no}/results.json"
    elif session_type == "Q":
        path = f"{season}/{round_no}/qualifying.json"
    elif session_type == "Sprint":
        path = f"{season}/{round_no}/sprint.json"
    else:
        log.info("No Jolpica endpoint for session type %s, skipping results", session_type)
        return

    try:
        data = _jolpica_get(path)
    except Exception as exc:
        log.warning("Jolpica fetch failed for %s: %s", path, exc)
        return

    try:
        race_data = data["MRData"]["RaceTable"]["Races"]
        if not race_data:
            log.warning("No race data in Jolpica response for %s", path)
            return
        result_list = race_data[0].get("Results") or race_data[0].get("QualifyingResults") or race_data[0].get("SprintResults", [])
    except (KeyError, IndexError) as exc:
        log.warning("Unexpected Jolpica structure for %s: %s", path, exc)
        return

    rows: list[dict] = []
    for r in result_list:
        code = r["Driver"].get("code", r["Driver"]["driverId"][:3].upper())
        driver_id = driver_map.get(code)
        if driver_id is None:
            log.warning("Driver code %s not in DB, skipping result row", code)
            continue

        pos_str = r.get("position") or r.get("positionText")
        try:
            position = int(pos_str) if pos_str and pos_str.isdigit() else None
        except (ValueError, TypeError):
            position = None

        grid_str = r.get("grid")
        try:
            grid = int(grid_str) if grid_str else None
        except (ValueError, TypeError):
            grid = None

        rows.append(
            {
                "session_id": session_id,
                "driver_id": driver_id,
                "grid": grid,
                "position": position,
                "status": r.get("status"),
                "points": float(r.get("points", 0) or 0),
            }
        )

    if not rows:
        return

    with engine.begin() as conn:
        # Delete existing results for this session before re-inserting
        conn.execute(text("DELETE FROM results WHERE session_id=:sid"), {"sid": session_id})
        conn.execute(
            text(
                """
                INSERT INTO results (session_id, driver_id, grid, position, status, points)
                VALUES (:session_id, :driver_id, :grid, :position, :status, :points)
                ON CONFLICT (session_id, driver_id) DO UPDATE SET
                    grid     = EXCLUDED.grid,
                    position = EXCLUDED.position,
                    status   = EXCLUDED.status,
                    points   = EXCLUDED.points
                """
            ),
            rows,
        )
    log.info("Upserted %d result rows for session_id=%d", len(rows), session_id)


# ---------------------------------------------------------------------------
# Laps loader (FastF1)
# ---------------------------------------------------------------------------


def _ff1_session_type(session_type: str) -> str:
    """Map our session type code to FastF1 session identifier string."""
    return {
        "Q": "Q",
        "R": "R",
        "Sprint": "S",
        "SQ": "SQ",
    }.get(session_type, session_type)


def _load_laps_jolpica(
    season: int,
    round_no: int,
    session_type: str,
    session_id: int,
    engine: Engine,
    run_id: str,
) -> bool:
    """Fallback loader: upsert laps from Jolpica API when FastF1 timing is unavailable."""
    slug_map = _get_driver_slug_map(season, engine)
    code_map = _get_driver_id_map(engine)

    if session_type in ("R", "Sprint"):
        # 1. Fetch pit stops to identify in-laps and out-laps
        pit_in_laps: set[tuple[int, int]] = set()
        pit_out_laps: set[tuple[int, int]] = set()
        try:
            ps_data = _jolpica_get(f"{season}/{round_no}/pitstops.json", params={"limit": 100})
            races = ps_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
            if races:
                for ps in races[0].get("PitStops", []):
                    did = slug_map.get(ps.get("driverId"))
                    lap = int(ps.get("lap", 0))
                    if did and lap > 0:
                        pit_in_laps.add((did, lap))
                        pit_out_laps.add((did, lap + 1))
        except Exception as exc:
            log.warning("Could not fetch pit stops from Jolpica for %d R%d: %s", season, round_no, exc)

        # 2. Paginate laps
        offset = 0
        rows: list[dict] = []
        while True:
            try:
                data = _jolpica_get(f"{season}/{round_no}/laps.json", params={"limit": 100, "offset": offset})
            except Exception as exc:
                log.warning("Jolpica laps request failed at offset %d: %s", offset, exc)
                break

            mr = data.get("MRData", {})
            races = mr.get("RaceTable", {}).get("Races", [])
            if not races:
                break
            laps = races[0].get("Laps", [])
            if not laps:
                break
            total = int(mr.get("total", 0))

            for lap_obj in laps:
                lap_no = int(lap_obj["number"])
                for t in lap_obj.get("Timings", []):
                    did = slug_map.get(t.get("driverId"))
                    if not did:
                        continue
                    t_ms = _parse_time_ms(t.get("time"))
                    pos_str = t.get("position", "")
                    pos = int(pos_str) if pos_str.isdigit() else None
                    is_in = (did, lap_no) in pit_in_laps
                    is_out = (did, lap_no) in pit_out_laps

                    rows.append({
                        "session_id": session_id,
                        "driver_id": did,
                        "lap_no": lap_no,
                        "lap_time_ms": t_ms,
                        "s1_ms": None,
                        "s2_ms": None,
                        "s3_ms": None,
                        "compound": "UNKNOWN",
                        "tyre_life": None,
                        "stint": None,
                        "pit_in_time": 1 if is_in else None,
                        "pit_out_time": 1 if is_out else None,
                        "track_status": "1",
                        "position": pos,
                        "is_accurate": True if t_ms else False,
                        "is_clean": False,
                    })

            offset += 100
            if offset >= total:
                break

        if not rows:
            log.warning("No Jolpica race laps found for %d R%d %s", season, round_no, session_type)
            return False

        df = pd.DataFrame(rows)
        flag_implausible_times(df)
        apply_clean_flag(df)
        _upsert_laps(df, session_id, engine)
        log.info("Upserted %d race laps from Jolpica for %d R%d %s", len(df), season, round_no, session_type)
        return True

    elif session_type in ("Q", "SQ"):
        path = f"{season}/{round_no}/qualifying.json" if session_type == "Q" else f"{season}/{round_no}/sprint.json"
        try:
            data = _jolpica_get(path)
            races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
            if not races:
                return False
            q_results = races[0].get("QualifyingResults") or races[0].get("SprintQualifyingResults", [])
        except Exception as exc:
            log.warning("Jolpica qualifying fetch failed for %d R%d: %s", season, round_no, exc)
            return False

        rows: list[dict] = []
        for r in q_results:
            drv = r.get("Driver", {})
            did = code_map.get(drv.get("code")) or slug_map.get(drv.get("driverId"))
            if not did:
                continue
            pos_str = r.get("position", "")
            pos = int(pos_str) if pos_str.isdigit() else 1

            for lap_idx, q_key in enumerate(["Q1", "Q2", "Q3"], start=1):
                t_str = r.get(q_key)
                t_ms = _parse_time_ms(t_str)
                if t_ms:
                    rows.append({
                        "session_id": session_id,
                        "driver_id": did,
                        "lap_no": lap_idx,
                        "lap_time_ms": t_ms,
                        "s1_ms": None,
                        "s2_ms": None,
                        "s3_ms": None,
                        "compound": "SOFT",
                        "tyre_life": 1,
                        "stint": lap_idx,
                        "pit_in_time": None,
                        "pit_out_time": None,
                        "track_status": "1",
                        "position": pos,
                        "is_accurate": True,
                        "is_clean": True,
                    })

        if not rows:
            return False

        df = pd.DataFrame(rows)
        _upsert_laps(df, session_id, engine)
        log.info("Upserted %d qualifying laps from Jolpica for %d R%d %s", len(df), season, round_no, session_type)
        return True

    return False


def load_laps(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
) -> None:
    """
    Load lap data for one session via FastF1 (falling back to Jolpica API if unavailable).

    Cleaning rules (is_clean) are applied here before writing.
    DQ checks are run and persisted to dq_log.
    """
    _configure_ff1_cache()

    label = f"{season} R{round_no} {session_type}"
    log.info("Loading laps: %s", label)

    event_id = _get_event_id(season, round_no, engine)
    if event_id is None:
        log.error("Event not in DB for %s – run load_events first", label)
        return

    session_id = _get_or_create_session(event_id, session_type, engine)
    driver_map = _get_driver_id_map(engine)

    sess = None
    try:
        ff1_type = _ff1_session_type(session_type)
        sess = fastf1.get_session(season, round_no, ff1_type)
        sess.load(laps=True, telemetry=False, weather=True, messages=True)
    except Exception as exc:
        dq_rows = check_session_load_failure(run_id, label, str(exc))
        write_dq_log(dq_rows, engine)
        log.warning("FastF1 session load failed for %s (%s) – falling back to Jolpica", label, exc)

    has_laps = False
    laps_data = None
    if sess is not None:
        try:
            laps_data = getattr(sess, "_laps", None)
            if laps_data is None:
                laps_data = sess.laps
            if laps_data is not None and not laps_data.empty:
                has_laps = True
        except Exception:
            has_laps = False

    if has_laps and laps_data is not None:
        # ---- Check driver codes against DB ----
        db_drivers_df = pd.DataFrame(list(driver_map.items()), columns=["code", "driver_id"])
        dq_rows = check_driver_number_mismatch(laps_data, db_drivers_df, run_id, label)
        write_dq_log(dq_rows, engine)

        # ---- Build laps DataFrame ----
        laps_df = laps_data.copy()
        laps_df = _map_laps_to_schema(laps_df, session_id, driver_map)

        if not laps_df.empty:
            # Apply cleaning rules
            flag_implausible_times(laps_df)
            apply_clean_flag(laps_df)

            # Run all DQ checks
            dq_rows = run_all_lap_checks(laps_df, run_id, label)
            write_dq_log(dq_rows, engine)

            # ---- Upsert laps ----
            _upsert_laps(laps_df, session_id, engine)
            log.info("Upserted %d laps for %s via FastF1", len(laps_df), label)
            return

    # Fallback to Jolpica
    log.info("Attempting Jolpica fallback for laps: %s", label)
    _load_laps_jolpica(season, round_no, session_type, session_id, engine, run_id)


def _map_laps_to_schema(
    laps_df: pd.DataFrame,
    session_id: int,
    driver_map: dict[str, int],
) -> pd.DataFrame:
    """
    Transform a FastF1 laps DataFrame into columns matching the laps table.

    FastF1 column mapping:
        Driver          -> code (looked up to driver_id)
        LapNumber       -> lap_no
        LapTime         -> lap_time_ms  (Timedelta -> ms)
        Sector1Time     -> s1_ms
        Sector2Time     -> s2_ms
        Sector3Time     -> s3_ms
        Compound        -> compound
        TyreLife        -> tyre_life
        Stint           -> stint
        PitInTime       -> pit_in_time  (ms from session start)
        PitOutTime      -> pit_out_time
        TrackStatus     -> track_status
        Position        -> position
        IsAccurate      -> is_accurate
    """
    def _td_ms(series: pd.Series) -> pd.Series:
        """Convert Timedelta series to integer milliseconds, NaT -> None."""
        return series.apply(
            lambda td: int(td.total_seconds() * 1000) if pd.notna(td) else None
        )

    out = pd.DataFrame(index=laps_df.index)
    out["session_id"] = int(session_id)
    out["driver_id"] = laps_df["Driver"].map(driver_map)
    out["lap_no"] = laps_df["LapNumber"].astype("Int64")
    out["lap_time_ms"] = _td_ms(laps_df["LapTime"])
    out["s1_ms"] = _td_ms(laps_df["Sector1Time"]) if "Sector1Time" in laps_df.columns else None
    out["s2_ms"] = _td_ms(laps_df["Sector2Time"]) if "Sector2Time" in laps_df.columns else None
    out["s3_ms"] = _td_ms(laps_df["Sector3Time"]) if "Sector3Time" in laps_df.columns else None
    out["compound"] = laps_df.get("Compound", pd.Series("UNKNOWN", index=laps_df.index))
    out["tyre_life"] = laps_df.get("TyreLife", pd.Series(dtype="Int64")).astype("Int64")
    out["stint"] = laps_df.get("Stint", pd.Series(dtype="Int64")).astype("Int64")
    out["pit_in_time"] = _td_ms(laps_df["PitInTime"]) if "PitInTime" in laps_df.columns else None
    out["pit_out_time"] = _td_ms(laps_df["PitOutTime"]) if "PitOutTime" in laps_df.columns else None
    out["track_status"] = laps_df.get("TrackStatus", pd.Series("1", index=laps_df.index)).astype(str)
    out["position"] = laps_df.get("Position", pd.Series(dtype="Int64")).astype("Int64")
    out["is_accurate"] = laps_df.get("IsAccurate", pd.Series(False, index=laps_df.index)).fillna(False).astype(bool)
    out["is_clean"] = False  # will be set by apply_clean_flag

    # Drop rows where driver_id could not be resolved
    before = len(out)
    out = out.dropna(subset=["driver_id"])
    dropped = before - len(out)
    if dropped:
        log.warning("Dropped %d laps with unmapped driver codes", dropped)

    out["driver_id"] = out["driver_id"].astype(int)
    out["lap_no"] = out["lap_no"].astype(int)
    return out.reset_index(drop=True)


def _upsert_laps(df: pd.DataFrame, session_id: int, engine: Engine) -> None:
    """Delete existing laps for this session and bulk-insert new ones."""
    int_cols = {
        "session_id", "driver_id", "lap_no", "lap_time_ms",
        "s1_ms", "s2_ms", "s3_ms", "tyre_life", "stint",
        "pit_in_time", "pit_out_time", "position",
    }
    raw_records = df.to_dict(orient="records")
    records = []
    for r in raw_records:
        row = {}
        for k, v in r.items():
            if pd.isna(v) or v is None:
                row[k] = None
            elif k in int_cols:
                row[k] = int(v)
            elif k in ("is_accurate", "is_clean"):
                row[k] = bool(v)
            elif k in ("compound", "track_status"):
                row[k] = str(v)
            else:
                row[k] = v
        row["session_id"] = int(session_id)
        records.append(row)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM laps WHERE session_id=:sid"), {"sid": session_id})
        if records:
            conn.execute(
                text(
                    """
                    INSERT INTO laps
                        (session_id, driver_id, lap_no, lap_time_ms,
                         s1_ms, s2_ms, s3_ms, compound, tyre_life, stint,
                         pit_in_time, pit_out_time, track_status, position,
                         is_accurate, is_clean)
                    VALUES
                        (:session_id, :driver_id, :lap_no, :lap_time_ms,
                         :s1_ms, :s2_ms, :s3_ms, :compound, :tyre_life, :stint,
                         :pit_in_time, :pit_out_time, :track_status, :position,
                         :is_accurate, :is_clean)
                    ON CONFLICT (session_id, driver_id, lap_no) DO UPDATE SET
                        lap_time_ms  = EXCLUDED.lap_time_ms,
                        s1_ms        = EXCLUDED.s1_ms,
                        s2_ms        = EXCLUDED.s2_ms,
                        s3_ms        = EXCLUDED.s3_ms,
                        compound     = EXCLUDED.compound,
                        tyre_life    = EXCLUDED.tyre_life,
                        stint        = EXCLUDED.stint,
                        pit_in_time  = EXCLUDED.pit_in_time,
                        pit_out_time = EXCLUDED.pit_out_time,
                        track_status = EXCLUDED.track_status,
                        position     = EXCLUDED.position,
                        is_accurate  = EXCLUDED.is_accurate,
                        is_clean     = EXCLUDED.is_clean
                    """
                ),
                records,
            )


# ---------------------------------------------------------------------------
# Pit stops loader
# ---------------------------------------------------------------------------


def _load_pit_stops_jolpica(
    season: int,
    round_no: int,
    session_type: str,
    session_id: int,
    engine: Engine,
    label: str,
) -> None:
    """Fallback loader: upsert pit stops from Jolpica when FastF1 is unavailable."""
    slug_map = _get_driver_slug_map(season, engine)
    try:
        ps_data = _jolpica_get(f"{season}/{round_no}/pitstops.json", params={"limit": 100})
        races = ps_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not races:
            return
        ps_list = races[0].get("PitStops", [])
    except Exception as exc:
        log.warning("Jolpica pit stops fetch failed for %s: %s", label, exc)
        return

    rows: list[dict] = []
    for ps in ps_list:
        did = slug_map.get(ps.get("driverId"))
        if not did:
            continue
        stop_no = int(ps.get("stop", 1))
        lap = int(ps.get("lap", 0))
        dur_ms = _parse_time_ms(ps.get("duration"))
        rows.append({
            "session_id": session_id,
            "driver_id": did,
            "stop_no": stop_no,
            "lap": lap,
            "pit_lane_time_ms": dur_ms,
        })

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pit_stops WHERE session_id=:sid"), {"sid": session_id})
        if rows:
            conn.execute(
                text(
                    """
                    INSERT INTO pit_stops
                        (session_id, driver_id, stop_no, lap, pit_lane_time_ms)
                    VALUES
                        (:session_id, :driver_id, :stop_no, :lap, :pit_lane_time_ms)
                    ON CONFLICT (session_id, driver_id, stop_no) DO UPDATE SET
                        lap              = EXCLUDED.lap,
                        pit_lane_time_ms = EXCLUDED.pit_lane_time_ms
                    """
                ),
                rows,
            )
    log.info("Upserted %d pit stop rows from Jolpica for %s", len(rows), label)


def load_pit_stops(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
) -> None:
    """
    Load pit stop data from FastF1 laps (falling back to Jolpica if unavailable).

    Only meaningful for 'R' and 'Sprint' sessions.
    """
    if session_type not in ("R", "Sprint"):
        log.info("Skipping pit stops for session type %s", session_type)
        return

    _configure_ff1_cache()
    label = f"{season} R{round_no} {session_type}"
    log.info("Loading pit stops: %s", label)

    event_id = _get_event_id(season, round_no, engine)
    if event_id is None:
        return
    session_id = _get_or_create_session(event_id, session_type, engine)
    driver_map = _get_driver_id_map(engine)

    sess = None
    try:
        ff1_type = _ff1_session_type(session_type)
        sess = fastf1.get_session(season, round_no, ff1_type)
        sess.load(laps=True, telemetry=False, weather=False, messages=False)
    except Exception as exc:
        log.warning("FastF1 load failed for pit stops %s: %s – falling back to Jolpica", label, exc)

    has_laps = False
    laps_data = None
    if sess is not None:
        try:
            laps_data = getattr(sess, "_laps", None)
            if laps_data is None:
                laps_data = sess.laps
            if laps_data is not None and not laps_data.empty:
                has_laps = True
        except Exception:
            has_laps = False

    if has_laps and laps_data is not None:
        laps = laps_data.copy()
        pit_laps = laps[laps["PitInTime"].notna()].copy() if "PitInTime" in laps.columns else pd.DataFrame()
        if not pit_laps.empty:
            rows: list[dict] = []
            stop_counter: dict[int, int] = {}
            for _, row in pit_laps.sort_values(["Driver", "LapNumber"]).iterrows():
                code = row["Driver"]
                driver_id = driver_map.get(code)
                if driver_id is None:
                    continue

                stop_counter[driver_id] = stop_counter.get(driver_id, 0) + 1
                stop_no = stop_counter[driver_id]

                pit_in = row.get("PitInTime")
                pit_out = row.get("PitOutTime")
                pit_lane_ms: int | None = None
                if pd.notna(pit_in) and pd.notna(pit_out):
                    pit_lane_ms = int((pit_out - pit_in).total_seconds() * 1000)

                rows.append({
                    "session_id": session_id,
                    "driver_id": driver_id,
                    "stop_no": stop_no,
                    "lap": int(row["LapNumber"]),
                    "pit_lane_time_ms": pit_lane_ms,
                })

            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pit_stops WHERE session_id=:sid"), {"sid": session_id})
                if rows:
                    conn.execute(
                        text(
                            """
                            INSERT INTO pit_stops
                                (session_id, driver_id, stop_no, lap, pit_lane_time_ms)
                            VALUES
                                (:session_id, :driver_id, :stop_no, :lap, :pit_lane_time_ms)
                            ON CONFLICT (session_id, driver_id, stop_no) DO UPDATE SET
                                lap              = EXCLUDED.lap,
                                pit_lane_time_ms = EXCLUDED.pit_lane_time_ms
                            """
                        ),
                        rows,
                    )
            log.info("Upserted %d pit stop rows for %s via FastF1", len(rows), label)
            return

    # Fallback to Jolpica
    _load_pit_stops_jolpica(season, round_no, session_type, session_id, engine, label)


# ---------------------------------------------------------------------------
# Race control loader
# ---------------------------------------------------------------------------


def load_race_control(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
) -> None:
    """Load race control messages from FastF1."""
    _configure_ff1_cache()
    label = f"{season} R{round_no} {session_type}"
    log.info("Loading race control: %s", label)

    try:
        ff1_type = _ff1_session_type(session_type)
        sess = fastf1.get_session(season, round_no, ff1_type)
        sess.load(laps=False, telemetry=False, weather=False, messages=True)
    except Exception as exc:
        log.error("FastF1 load failed for race control %s: %s", label, exc)
        return

    event_id = _get_event_id(season, round_no, engine)
    if event_id is None:
        return
    session_id = _get_or_create_session(event_id, session_type, engine)

    try:
        rc = getattr(sess, "_race_control_messages", None)
        if rc is None:
            rc = sess.race_control_messages
    except Exception:
        log.warning("race_control_messages not available for %s", label)
        return

    if rc is None or rc.empty:
        log.info("No race control messages for %s", label)
        return

    def _to_ms(val: Any) -> int:
        if pd.isna(val) or val is None:
            return 0
        if hasattr(val, "total_seconds"):
            return int(val.total_seconds() * 1000)
        if hasattr(val, "timestamp"):
            return int(val.timestamp() * 1000)
        return int(val)

    rows: list[dict] = []
    for _, row in rc.iterrows():
        time_ms = _to_ms(row.get("Time"))

        rows.append(
            {
                "session_id": session_id,
                "time": time_ms or 0,
                "lap": int(row["Lap"]) if pd.notna(row.get("Lap")) else None,
                "category": row.get("Category"),
                "flag": row.get("Flag"),
                "message": str(row.get("Message", "")),
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM race_control WHERE session_id=:sid"), {"sid": session_id})
        if rows:
            conn.execute(
                text(
                    """
                    INSERT INTO race_control
                        (session_id, time, lap, category, flag, message)
                    VALUES
                        (:session_id, :time, :lap, :category, :flag, :message)
                    ON CONFLICT (session_id, time, message) DO NOTHING
                    """
                ),
                rows,
            )
    log.info("Upserted %d race control rows for %s", len(rows), label)


# ---------------------------------------------------------------------------
# Weather loader
# ---------------------------------------------------------------------------


def load_weather(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
) -> None:
    """Load weather samples from FastF1."""
    _configure_ff1_cache()
    label = f"{season} R{round_no} {session_type}"
    log.info("Loading weather: %s", label)

    try:
        ff1_type = _ff1_session_type(session_type)
        sess = fastf1.get_session(season, round_no, ff1_type)
        sess.load(laps=False, telemetry=False, weather=True, messages=False)
    except Exception as exc:
        log.error("FastF1 load failed for weather %s: %s", label, exc)
        return

    event_id = _get_event_id(season, round_no, engine)
    if event_id is None:
        return
    session_id = _get_or_create_session(event_id, session_type, engine)

    try:
        weather_df = getattr(sess, "_weather_data", None)
        if weather_df is None:
            weather_df = sess.weather_data
    except Exception:
        log.warning("weather_data not available for %s", label)
        return

    if weather_df is None or weather_df.empty:
        log.info("No weather data for %s", label)
        return

    rows: list[dict] = []
    for _, row in weather_df.iterrows():
        t = row.get("Time")
        if pd.isna(t) or t is None:
            time_ms = 0
        elif hasattr(t, "total_seconds"):
            time_ms = int(t.total_seconds() * 1000)
        elif hasattr(t, "timestamp"):
            time_ms = int(t.timestamp() * 1000)
        else:
            time_ms = int(t)

        rows.append(
            {
                "session_id": session_id,
                "time": time_ms,
                "air_temp": float(row["AirTemp"]) if pd.notna(row.get("AirTemp")) else None,
                "track_temp": float(row["TrackTemp"]) if pd.notna(row.get("TrackTemp")) else None,
                "rainfall": bool(row["Rainfall"]) if pd.notna(row.get("Rainfall")) else None,
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM weather WHERE session_id=:sid"), {"sid": session_id})
        if rows:
            conn.execute(
                text(
                    """
                    INSERT INTO weather
                        (session_id, time, air_temp, track_temp, rainfall)
                    VALUES
                        (:session_id, :time, :air_temp, :track_temp, :rainfall)
                    ON CONFLICT (session_id, time) DO UPDATE SET
                        air_temp   = EXCLUDED.air_temp,
                        track_temp = EXCLUDED.track_temp,
                        rainfall   = EXCLUDED.rainfall
                    """
                ),
                rows,
            )
    log.info("Upserted %d weather rows for %s", len(rows), label)


# ---------------------------------------------------------------------------
# Convenience: load one full race weekend
# ---------------------------------------------------------------------------


def load_race_weekend(
    season: int,
    round_no: int,
    engine: Engine,
    run_id: str | None = None,
    session_types: list[str] | None = None,
) -> None:
    """
    Load all data for one race weekend.

    session_types defaults to ['Q', 'R']. Pass ['Q', 'Sprint', 'SQ', 'R']
    for sprint weekends.
    """
    if run_id is None:
        run_id = new_run_id()
    if session_types is None:
        session_types = ["Q", "R"]

    log.info(
        "=== Loading race weekend: season=%d round=%d sessions=%s run_id=%s ===",
        season, round_no, session_types, run_id,
    )

    for stype in session_types:
        load_results(season, round_no, stype, engine, run_id)
        load_laps(season, round_no, stype, engine, run_id)
        load_pit_stops(season, round_no, stype, engine, run_id)
        load_race_control(season, round_no, stype, engine, run_id)
        load_weather(season, round_no, stype, engine, run_id)

    log.info("=== Completed loading round %d ===", round_no)
