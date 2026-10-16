"""
etl/season.py – Full-season ETL orchestrator for the 2025 F1 season.

Usage:
    from etl.season import load_full_season
    load_full_season(season=2025, engine=engine, run_id=run_id)

Design:
- Iterates every round in the events table (populated by load_events first).
- Skips rounds that haven't happened yet (date > today).
- Identifies sprint weekends from the round name / Jolpica data.
- Handles per-session failures gracefully: log, skip, continue.
- Progress is printed so long runs are observable.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.ingest import (
    load_drivers_and_teams,
    load_events,
    load_laps,
    load_pit_stops,
    load_race_control,
    load_results,
    load_weather,
)
from etl.quality import new_run_id

log = logging.getLogger(__name__)

# Rounds known to be sprint weekends in 2025.
# Source: official F1 calendar released January 2025.
# Update this list if the calendar changes mid-season.
SPRINT_ROUNDS_2025: frozenset[int] = frozenset({
    6,   # Chinese GP – Shanghai
    11,  # Austrian GP – Spielberg (provisional; verify against Jolpica)
    16,  # US GP – Austin
    18,  # São Paulo GP – Interlagos
    20,  # Qatar GP – Lusail
    22,  # Las Vegas GP – Las Vegas Strip
})


def _get_all_rounds(season: int, engine: Engine) -> list[dict[str, Any]]:
    """Return all events for a season as a list of dicts, ordered by round."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_id, round, name, date
                FROM events
                WHERE season = :season
                ORDER BY round
                """
            ),
            {"season": season},
        ).fetchall()
    return [{"event_id": r[0], "round": r[1], "name": r[2], "date": r[3]} for r in rows]


def _session_types_for_round(round_no: int, season: int) -> list[str]:
    """Return the list of session types for this round in order."""
    if season == 2025 and round_no in SPRINT_ROUNDS_2025:
        return ["SQ", "Sprint", "Q", "R"]
    return ["Q", "R"]


def load_full_season(
    season: int,
    engine: Engine,
    run_id: str | None = None,
    skip_future: bool = True,
    rounds: list[int] | None = None,
) -> None:
    """
    Load the complete season for all (past) rounds.

    Parameters
    ----------
    season      : Championship year (e.g. 2025).
    engine      : SQLAlchemy engine.
    run_id      : ETL run identifier. Generated if not supplied.
    skip_future : If True, rounds with date > today are skipped.
    rounds      : If provided, only load these specific round numbers.
    """
    if run_id is None:
        run_id = new_run_id()

    today = datetime.date.today()

    log.info("=== Full season load: season=%d run_id=%s ===", season, run_id)

    # Ensure events and drivers are loaded first
    log.info("Refreshing events …")
    load_events(season, engine, run_id)

    log.info("Refreshing drivers/teams …")
    load_drivers_and_teams(season, engine, run_id)

    all_rounds = _get_all_rounds(season, engine)
    if not all_rounds:
        log.error("No events found for season %d — aborting", season)
        return

    total = len(all_rounds)
    log.info("Found %d rounds in season %d", total, season)

    for idx, event in enumerate(all_rounds, 1):
        rnd = event["round"]
        name = event["name"]
        date = event["date"]

        if rounds is not None and rnd not in rounds:
            log.debug("Skipping round %d (%s) — not in requested rounds list", rnd, name)
            continue

        if skip_future and isinstance(date, datetime.date) and date > today:
            log.info(
                "Skipping round %d (%s, %s) — race not yet run",
                rnd,
                name,
                date,
            )
            continue

        session_types = _session_types_for_round(rnd, season)
        log.info(
            "[%d/%d] Loading round %d – %s (sessions: %s)",
            idx,
            total,
            rnd,
            name,
            ", ".join(session_types),
        )

        for stype in session_types:
            _load_session_safe(season, rnd, stype, engine, run_id, name)

    from etl.views import refresh_views
    log.info("Refreshing materialized views for season %d …", season)
    refresh_views(engine)

    log.info("=== Season %d load complete (run_id=%s) ===", season, run_id)


def _load_session_safe(
    season: int,
    round_no: int,
    session_type: str,
    engine: Engine,
    run_id: str,
    event_name: str,
) -> None:
    """
    Load one session's worth of data. Catches all exceptions so a single
    bad session never aborts the whole season run.
    """
    label = f"{season} R{round_no} {session_type} ({event_name})"
    try:
        load_results(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("results load failed for %s: %s", label, exc)

    try:
        load_laps(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("laps load failed for %s: %s", label, exc)

    try:
        load_pit_stops(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("pit_stops load failed for %s: %s", label, exc)

    try:
        load_race_control(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("race_control load failed for %s: %s", label, exc)

    try:
        load_weather(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("weather load failed for %s: %s", label, exc)

    try:
        from etl.telemetry import load_telemetry_for_session
        load_telemetry_for_session(season, round_no, session_type, engine, run_id)
    except Exception as exc:  # noqa: BLE001
        log.error("telemetry load failed for %s: %s", label, exc)
