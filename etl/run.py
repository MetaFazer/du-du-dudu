"""
etl/run.py – CLI entry point for running ETL phases.

Usage:
    python -m etl.run --schema-only              # apply schema only
    python -m etl.run --season 2025 --round 1   # one round (Q + R)
    python -m etl.run --season 2025 --round 1 --sprint  # sprint weekend
    python -m etl.run --season 2025 --full-season        # all past rounds
    python -m etl.run --season 2025 --full-season --rounds 1,3,5  # subset
    python -m etl.run --season 2025 --views      # refresh materialized views
"""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Du-Du-Dudu ETL runner")
    parser.add_argument("--season", type=int, default=2025, help="F1 season year")
    parser.add_argument("--round", type=int, dest="round_no", help="Single round number")
    parser.add_argument("--rounds", type=str, help="Comma-separated round numbers, e.g. 1,3,5")
    parser.add_argument("--sprint", action="store_true", help="Force sprint sessions for --round")
    parser.add_argument("--full-season", action="store_true", help="Load all past rounds")
    parser.add_argument("--include-future", action="store_true", help="Don't skip future rounds")
    parser.add_argument("--schema-only", action="store_true", help="Only apply schema")
    parser.add_argument("--views", action="store_true", help="Refresh materialized views")
    parser.add_argument("--telemetry", action="store_true", help="Load telemetry & corner stats for sessions")
    args = parser.parse_args()

    from etl.db import apply_schema, get_engine
    from etl.quality import new_run_id

    engine = get_engine()
    log.info("Applying schema …")
    apply_schema(engine)

    if args.schema_only:
        log.info("--schema-only flag set, done.")
        return 0

    run_id = new_run_id()

    if args.views:
        from etl.views import refresh_views
        log.info("Refreshing materialized views …")
        refresh_views(engine)
        return 0

    if args.full_season:
        from etl.season import load_full_season

        round_filter = None
        if args.rounds:
            round_filter = [int(r.strip()) for r in args.rounds.split(",")]

        load_full_season(
            season=args.season,
            engine=engine,
            run_id=run_id,
            skip_future=not args.include_future,
            rounds=round_filter,
        )
        return 0

    # Single-round mode
    from etl.ingest import load_drivers_and_teams, load_events, load_race_weekend

    log.info("Loading events for season %d …", args.season)
    load_events(args.season, engine, run_id)

    log.info("Loading drivers/teams for season %d …", args.season)
    load_drivers_and_teams(args.season, engine, run_id)

    if args.round_no:
        session_types = ["Q", "R"]
        if args.sprint:
            session_types = ["SQ", "Sprint", "Q", "R"]
        if not args.telemetry:
            load_race_weekend(args.season, args.round_no, engine, run_id, session_types)

        if args.telemetry:
            from etl.telemetry import load_telemetry_for_session
            for stype in session_types:
                log.info("Loading telemetry: season %d round %d %s", args.season, args.round_no, stype)
                load_telemetry_for_session(args.season, args.round_no, stype, engine, run_id)
    else:
        log.info("No --round or --full-season specified. Loaded events and drivers only.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

