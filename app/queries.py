"""
app/queries.py – Cached, read-only SQL helpers for Streamlit pages.

All functions:
  • Use st.cache_data with a sensible TTL so the DB is not hammered on reruns.
  • Return pd.DataFrame (never raw SQLAlchemy Row objects).
  • Fail gracefully — if the DB has no data yet they return an empty DataFrame.
  • Never aggregate raw data in Python; they read from materialized views only.
"""

from __future__ import annotations

import logging
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton engine (separate from etl.db so Streamlit doesn't need the ETL
# module on sys.path in production).
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "")
    if not url and hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
        url = st.secrets["DATABASE_URL"]
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Please provide DATABASE_URL in .env or Streamlit Secrets."
        )
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://") and "+psycopg" not in url:
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_engine(
        url,
        connect_args={"prepare_threshold": None},
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
    )


def _q(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute a SQL string and return a DataFrame. Returns empty DF on error."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("DB query failed: %s", exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Season / calendar
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_events(season: int = 2025) -> pd.DataFrame:
    """All events for a season ordered by round number."""
    return _q(
        "SELECT event_id, round, name, circuit, country, date "
        "FROM events WHERE season = :season ORDER BY round",
        {"season": season},
    )


@st.cache_data(ttl=3600)
def get_sessions(event_id: int) -> pd.DataFrame:
    """All sessions for a given event (Q, R, Sprint, SQ)."""
    return _q(
        "SELECT session_id, type FROM sessions WHERE event_id = :eid ORDER BY session_id",
        {"eid": event_id},
    )


@st.cache_data(ttl=3600)
def get_drivers(season: int = 2025) -> pd.DataFrame:
    """All drivers + team name for a season."""
    return _q(
        """
        SELECT d.driver_id, d.code, d.full_name, d.number, t.name AS team_name, t.color_hex
        FROM drivers d
        JOIN entries e  ON e.driver_id = d.driver_id AND e.season = :season
        JOIN teams  t   ON t.team_id   = e.team_id
        ORDER BY d.code
        """,
        {"season": season},
    )


# ---------------------------------------------------------------------------
# Race – grid vs finish
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def get_grid_vs_finish(session_id: int) -> pd.DataFrame:
    """Positions gained/lost and DNF flag for a race session."""
    return _q(
        """
        SELECT gvf.driver_id, d.code, d.full_name, d.number,
               t.name AS team_name, t.color_hex,
               gvf.grid, gvf.position, gvf.status,
               gvf.is_dnf, gvf.places_gained
        FROM mv_grid_vs_finish gvf
        JOIN drivers d ON d.driver_id = gvf.driver_id
        JOIN sessions s ON s.session_id = gvf.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = gvf.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE gvf.session_id = :sid
        ORDER BY gvf.position NULLS LAST
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_results(session_id: int) -> pd.DataFrame:
    """Raw results for a session (qualifying or race)."""
    return _q(
        """
        SELECT r.driver_id, d.code, d.full_name, d.number,
               t.name AS team_name, t.color_hex,
               r.grid, r.position, r.status, r.points
        FROM results r
        JOIN drivers d ON d.driver_id = r.driver_id
        JOIN sessions s ON s.session_id = r.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = r.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE r.session_id = :sid
        ORDER BY r.position NULLS LAST
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_race_control(session_id: int) -> pd.DataFrame:
    """Race control messages (flags, SC, VSC) for a session."""
    return _q(
        "SELECT time, lap, category, flag, message "
        "FROM race_control WHERE session_id = :sid ORDER BY time",
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_reliability(season: int = 2025) -> pd.DataFrame:
    """DNF counts by team for a season."""
    return _q(
        """
        SELECT team_name, total_races, dnf_count,
               mechanical_dnf_count, incident_dnf_count,
               ROUND(100.0 * dnf_count / NULLIF(total_races, 0), 1) AS dnf_pct
        FROM mv_reliability
        WHERE season = :season
        ORDER BY dnf_count DESC
        """,
        {"season": season},
    )


# ---------------------------------------------------------------------------
# Pace analysis
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def get_clean_lap_pace(session_id: int) -> pd.DataFrame:
    """Median clean lap pace per driver for a session."""
    return _q(
        """
        SELECT cp.driver_id, d.code, d.full_name, t.name AS team_name, t.color_hex,
               cp.clean_lap_count, cp.median_ms, cp.p25_ms, cp.p75_ms,
               cp.best_ms, cp.stddev_ms
        FROM mv_clean_lap_pace cp
        JOIN drivers d ON d.driver_id = cp.driver_id
        JOIN sessions s ON s.session_id = cp.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = cp.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE cp.session_id = :sid
        ORDER BY cp.median_ms
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_laps(session_id: int) -> pd.DataFrame:
    """All laps for a session with driver and team metadata."""
    return _q(
        """
        SELECT l.lap_id, l.driver_id, d.code, d.full_name,
               t.name AS team_name, t.color_hex,
               l.lap_no, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms,
               l.compound, l.tyre_life, l.stint,
               l.pit_in_time, l.pit_out_time, l.track_status,
               l.position, l.is_accurate, l.is_clean
        FROM laps l
        JOIN drivers d ON d.driver_id = l.driver_id
        JOIN sessions s ON s.session_id = l.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = l.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE l.session_id = :sid
        ORDER BY l.driver_id, l.lap_no
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_tyre_deg(circuit: str) -> pd.DataFrame:
    """Tyre degradation data for a circuit (all compounds, clean laps)."""
    return _q(
        """
        SELECT td.session_id, td.driver_id, d.code,
               td.circuit, td.compound, td.tyre_life, td.lap_no,
               td.lap_time_ms, td.delta_from_median_ms
        FROM mv_tyre_deg td
        JOIN drivers d ON d.driver_id = td.driver_id
        WHERE td.circuit = :circuit
        ORDER BY td.compound, td.tyre_life
        """,
        {"circuit": circuit},
    )


@st.cache_data(ttl=600)
def get_teammate_gap(season: int = 2025) -> pd.DataFrame:
    """Qualifying and race pace gaps between teammates."""
    return _q(
        """
        SELECT tg.season, tg.team_id, t.name AS team_name,
               da.code AS driver_a_code, da.full_name AS driver_a_name,
               db.code AS driver_b_code, db.full_name AS driver_b_name,
               tg.q_gap_ms, tg.race_gap_ms,
               tg.driver_a_q_ms, tg.driver_b_q_ms,
               tg.driver_a_race_ms, tg.driver_b_race_ms
        FROM mv_teammate_gap tg
        JOIN teams   t  ON t.team_id   = tg.team_id
        JOIN drivers da ON da.driver_id = tg.driver_a_id
        JOIN drivers db ON db.driver_id = tg.driver_b_id
        WHERE tg.season = :season
        ORDER BY t.name
        """,
        {"season": season},
    )


# ---------------------------------------------------------------------------
# Pit stops
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def get_pit_loss(session_id: int) -> pd.DataFrame:
    """Estimated pit lane delta per stop (labeled estimated in UI)."""
    return _q(
        """
        SELECT pl.driver_id, d.code, d.full_name,
               t.name AS team_name, t.color_hex,
               pl.in_lap_no, pl.out_lap_no,
               pl.in_lap_ms, pl.out_lap_ms, pl.combined_ms,
               pl.ref_median_ms, pl.pit_loss_ms_est, pl.pit_lane_time_ms
        FROM mv_pit_loss pl
        JOIN drivers d ON d.driver_id = pl.driver_id
        JOIN sessions s ON s.session_id = pl.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = pl.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE pl.session_id = :sid
        ORDER BY pl.pit_loss_ms_est NULLS LAST
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_undercut(session_id: int) -> pd.DataFrame:
    """Undercut attempt outcomes for a race session (estimated)."""
    return _q(
        """
        SELECT u.driver_first, da.code AS first_code, da.full_name AS first_name,
               u.driver_second, db.code AS second_code, db.full_name AS second_name,
               u.first_in_lap, u.second_in_lap,
               u.first_pos_before, u.second_pos_before,
               u.first_pos_after, u.second_pos_after,
               u.undercut_success
        FROM mv_undercut u
        JOIN drivers da ON da.driver_id = u.driver_first
        JOIN drivers db ON db.driver_id = u.driver_second
        WHERE u.session_id = :sid
        ORDER BY u.first_in_lap
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_pit_stops(session_id: int) -> pd.DataFrame:
    """Raw pit stop data with lap and pit lane time."""
    return _q(
        """
        SELECT ps.driver_id, d.code, d.full_name,
               t.name AS team_name, t.color_hex,
               ps.stop_no, ps.lap, ps.pit_lane_time_ms
        FROM pit_stops ps
        JOIN drivers d ON d.driver_id = ps.driver_id
        JOIN sessions s ON s.session_id = ps.session_id
        JOIN events ev  ON ev.event_id  = s.event_id
        JOIN entries e  ON e.driver_id  = ps.driver_id AND e.season = ev.season
        JOIN teams t    ON t.team_id    = e.team_id
        WHERE ps.session_id = :sid
        ORDER BY ps.driver_id, ps.stop_no
        """,
        {"sid": session_id},
    )


# ---------------------------------------------------------------------------
# Phase 4 – Telemetry & Corner Analysis
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def get_telemetry_drivers(session_id: int) -> pd.DataFrame:
    """Return drivers who have fastest lap telemetry loaded for a session."""
    return _q(
        """
        SELECT DISTINCT t.driver_id, d.code, d.full_name, d.number,
               tm.name AS team_name, tm.color_hex, t.lap_no,
               l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms
        FROM telemetry_lap t
        JOIN drivers d   ON d.driver_id   = t.driver_id
        JOIN sessions s  ON s.session_id  = t.session_id
        JOIN events ev   ON ev.event_id   = s.event_id
        JOIN entries e   ON e.driver_id   = t.driver_id AND e.season = ev.season
        JOIN teams tm    ON tm.team_id    = e.team_id
        LEFT JOIN laps l ON l.session_id  = t.session_id AND l.driver_id = t.driver_id AND l.lap_no = t.lap_no
        WHERE t.session_id = :sid
        ORDER BY l.lap_time_ms ASC NULLS LAST
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_lap_telemetry(session_id: int, driver_id: int) -> pd.DataFrame:
    """Return 10m grid telemetry for one driver in a session."""
    return _q(
        """
        SELECT dist_m, speed, throttle, brake, gear, rpm, drs, x, y
        FROM telemetry_lap
        WHERE session_id = :sid AND driver_id = :did
        ORDER BY dist_m ASC
        """,
        {"sid": session_id, "did": driver_id},
    )


@st.cache_data(ttl=3600)
def get_circuit_corners(session_id: int) -> pd.DataFrame:
    """Return circuit corner coordinates and track distance for a session."""
    return _q(
        """
        SELECT c.corner_no, c.dist_m, c.x, c.y
        FROM corners c
        JOIN events ev ON ev.circuit = c.circuit
        JOIN sessions s ON s.event_id = ev.event_id
        WHERE s.session_id = :sid
        ORDER BY c.corner_no ASC
        """,
        {"sid": session_id},
    )


@st.cache_data(ttl=600)
def get_corner_stats(session_id: int, driver_ids: list[int] | None = None) -> pd.DataFrame:
    """Return corner statistics for drivers in a session."""
    if driver_ids:
        id_list = ",".join(str(int(i)) for i in driver_ids)
        sql = f"""
            SELECT cs.corner_no, cs.driver_id, d.code, tm.color_hex,
                   cs.brake_point_m, cs.min_speed, cs.throttle_pickup_m, cs.exit_speed
            FROM corner_stats cs
            JOIN drivers d   ON d.driver_id  = cs.driver_id
            JOIN sessions s  ON s.session_id = cs.session_id
            JOIN events ev   ON ev.event_id  = s.event_id
            JOIN entries e   ON e.driver_id  = cs.driver_id AND e.season = ev.season
            JOIN teams tm    ON tm.team_id   = e.team_id
            WHERE cs.session_id = :sid AND cs.driver_id IN ({id_list})
            ORDER BY cs.corner_no, cs.driver_id
        """
    else:
        sql = """
            SELECT cs.corner_no, cs.driver_id, d.code, tm.color_hex,
                   cs.brake_point_m, cs.min_speed, cs.throttle_pickup_m, cs.exit_speed
            FROM corner_stats cs
            JOIN drivers d   ON d.driver_id  = cs.driver_id
            JOIN sessions s  ON s.session_id = cs.session_id
            JOIN events ev   ON ev.event_id  = s.event_id
            JOIN entries e   ON e.driver_id  = cs.driver_id AND e.season = ev.season
            JOIN teams tm    ON tm.team_id   = e.team_id
            WHERE cs.session_id = :sid
            ORDER BY cs.corner_no, cs.driver_id
        """
    return _q(sql, {"sid": session_id})

