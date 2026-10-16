"""
etl/stints.py – Enrich laps with tyre compounds, tyre life, and stints from OpenF1,
and populate race control messages across the season.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.clean import WET_INTERMEDIATE_COMPOUNDS
from etl.db import get_engine
from etl.views import refresh_views

log = logging.getLogger(__name__)

OPENF1_BASE = "https://api.openf1.org/v1"


def enrich_season_stints(season: int = 2025, engine: Engine | None = None) -> None:
    """
    Fetch stints and race control messages from OpenF1 and update laps and race_control.
    """
    if engine is None:
        engine = get_engine()

    log.info("Fetching OpenF1 sessions for season %d …", season)
    try:
        resp = requests.get(f"{OPENF1_BASE}/sessions?year={season}", timeout=20)
        resp.raise_for_status()
        of1_sessions = resp.json()
    except Exception as exc:
        log.error("Failed to fetch OpenF1 sessions: %s", exc)
        return

    # Driver number to driver_id map
    with engine.connect() as conn:
        num_to_did = dict(
            conn.execute(text("SELECT number, driver_id FROM drivers WHERE number IS NOT NULL")).fetchall()
        )
        db_events = conn.execute(
            text("SELECT event_id, round, name, date, circuit FROM events WHERE season = :s ORDER BY round"),
            {"s": season},
        ).fetchall()
        db_sessions = conn.execute(
            text(
                """
                SELECT s.session_id, s.event_id, s.type
                FROM sessions s
                JOIN events e ON e.event_id = s.event_id
                WHERE e.season = :s
                """
            ),
            {"s": season},
        ).fetchall()

    event_sess: dict[int, dict[str, int]] = {}
    for s in db_sessions:
        event_sess.setdefault(s[1], {})[s[2]] = s[0]

    type_mapping = {
        "Race": "R",
        "Sprint": "Sprint",
    }

    total_stints_updated = 0
    total_rc_inserted = 0

    for ev in db_events:
        eid, rnd, name, dt, circuit = ev
        d_ev = dt if isinstance(dt, datetime.date) else datetime.date.fromisoformat(str(dt))

        # Find OpenF1 sessions within 4 days of event date
        weekend_of1 = []
        for of1 in of1_sessions:
            d_of1 = datetime.date.fromisoformat(of1["date_start"][:10])
            if abs((d_ev - d_of1).days) <= 4:
                weekend_of1.append(of1)

        for of1_name, db_type in type_mapping.items():
            matched_of1 = next((s for s in weekend_of1 if s.get("session_name") == of1_name), None)
            if not matched_of1:
                continue

            session_id = event_sess.get(eid, {}).get(db_type)
            if not session_id:
                continue

            sk = matched_of1["session_key"]
            log.info("Processing %s R%d %s (%s) -> OpenF1 session_key=%d", season, rnd, name, db_type, sk)

            # 1. Fetch stints
            try:
                time.sleep(0.15)
                s_resp = requests.get(f"{OPENF1_BASE}/stints?session_key={sk}", timeout=15)
                if s_resp.status_code == 200:
                    stints = s_resp.json()
                    stint_updates = 0
                    with engine.begin() as conn:
                        for st in stints:
                            num = st.get("driver_number")
                            did = num_to_did.get(num)
                            if not did:
                                continue
                            compound = str(st.get("compound", "")).upper()
                            stint_no = st.get("stint_number")
                            l_start = st.get("lap_start")
                            l_end = st.get("lap_end")
                            tyre_age = st.get("tyre_age_at_start", 0) or 0
                            if not (l_start and l_end and compound):
                                continue

                            is_wet = compound in WET_INTERMEDIATE_COMPOUNDS

                            # Update laps for this driver
                            res = conn.execute(
                                text(
                                    """
                                    UPDATE laps
                                    SET compound = :compound,
                                        stint = :stint_no,
                                        tyre_life = :tyre_age + (lap_no - :l_start + 1),
                                        is_clean = CASE WHEN :is_wet THEN FALSE ELSE is_clean END
                                    WHERE session_id = :sid
                                      AND driver_id = :did
                                      AND lap_no >= :l_start
                                      AND lap_no <= :l_end
                                    """
                                ),
                                {
                                    "compound": compound,
                                    "stint_no": stint_no,
                                    "tyre_age": tyre_age,
                                    "l_start": l_start,
                                    "l_end": l_end,
                                    "is_wet": is_wet,
                                    "sid": session_id,
                                    "did": did,
                                },
                            )
                            stint_updates += res.rowcount
                    log.info("  -> Updated %d laps with compound/stint info", stint_updates)
                    total_stints_updated += stint_updates
            except Exception as exc:
                log.warning("Could not fetch stints for session_key %d: %s", sk, exc)

            # 2. Fetch race control
            try:
                time.sleep(0.15)
                rc_resp = requests.get(f"{OPENF1_BASE}/race_control?session_key={sk}", timeout=15)
                if rc_resp.status_code == 200:
                    rc_messages = rc_resp.json()
                    rc_rows = []
                    for rc in rc_messages:
                        msg_time = rc.get("date")
                        t_ms = 0
                        if msg_time:
                            try:
                                dt_msg = datetime.datetime.fromisoformat(msg_time)
                                t_ms = int(dt_msg.timestamp() * 1000)
                            except Exception:
                                t_ms = 0
                        rc_rows.append(
                            {
                                "session_id": session_id,
                                "time": t_ms,
                                "lap": rc.get("lap_number"),
                                "category": rc.get("category"),
                                "flag": rc.get("flag"),
                                "message": rc.get("message", ""),
                            }
                        )
                    if rc_rows:
                        with engine.begin() as conn:
                            conn.execute(text("DELETE FROM race_control WHERE session_id=:sid"), {"sid": session_id})
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO race_control (session_id, time, lap, category, flag, message)
                                    VALUES (:session_id, :time, :lap, :category, :flag, :message)
                                    ON CONFLICT (session_id, time, message) DO NOTHING
                                    """
                                ),
                                rc_rows,
                            )
                        log.info("  -> Inserted %d race control messages", len(rc_rows))
                        total_rc_inserted += len(rc_rows)
            except Exception as exc:
                log.warning("Could not fetch race control for session_key %d: %s", sk, exc)

    log.info("=== Enrichment complete: %d laps updated, %d race control rows inserted ===", total_stints_updated, total_rc_inserted)
    log.info("Refreshing materialized views …")
    refresh_views(engine)
    log.info("All views refreshed.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    enrich_season_stints(2025)
