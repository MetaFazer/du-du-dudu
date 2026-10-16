"""
etl/views.py – Create and refresh PostgreSQL materialized views.

Called after data is loaded to pre-aggregate heavy queries.
The Streamlit app reads from these views; it never runs the raw aggregates live.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


def apply_views(engine: Engine) -> None:
    """Execute sql/views.sql to create all materialized views (idempotent)."""
    views_path = Path(__file__).parent.parent / "sql" / "views.sql"
    sql = views_path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
    log.info("Materialized views applied from %s", views_path)


def refresh_views(engine: Engine) -> None:
    """
    REFRESH all materialized views concurrently.

    CONCURRENTLY requires a UNIQUE index on each view (already created in views.sql).
    It allows reads to continue while the view refreshes.
    """
    views = [
        "mv_clean_lap_pace",
        "mv_pit_loss",
        "mv_tyre_deg",
        "mv_teammate_gap",
        "mv_grid_vs_finish",
        "mv_reliability",
        "mv_undercut",
    ]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for view in views:
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
                log.info("Refreshed %s", view)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not refresh %s: %s", view, exc)
