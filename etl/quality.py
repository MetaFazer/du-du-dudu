"""
etl/quality.py – Data quality checks logged to the dq_log table.

Each check is a function that:
  - Accepts a DataFrame (or engine) and a run_id string.
  - Returns a list of dq_log row dicts.
  - Never raises; it only logs.

The write_dq_log() helper persists the collected rows to the database.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(
    run_id: str,
    table_name: str,
    check_name: str,
    severity: str,
    row_count: int | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "table_name": table_name,
        "check_name": check_name,
        "severity": severity,
        "row_count": row_count,
        "detail": detail,
    }


def write_dq_log(rows: list[dict[str, Any]], engine: Engine) -> None:
    """Persist a list of dq_log row dicts to the database."""
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO dq_log
                    (run_id, table_name, check_name, severity, row_count, detail)
                VALUES
                    (:run_id, :table_name, :check_name, :severity, :row_count, :detail)
                """
            ),
            rows,
        )
    log.debug("Wrote %d DQ log rows", len(rows))


def new_run_id() -> str:
    """Generate a unique ETL run identifier."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Lap-level checks (operate on the laps DataFrame before writing to DB)
# ---------------------------------------------------------------------------


def check_null_lap_times(
    df: pd.DataFrame, run_id: str, session_label: str
) -> list[dict[str, Any]]:
    """Check for rows where lap_time_ms is null."""
    null_count = df["lap_time_ms"].isna().sum()
    severity = "WARNING" if null_count > 0 else "INFO"
    return [
        _row(
            run_id,
            "laps",
            "null_lap_times",
            severity,
            int(null_count),
            f"session={session_label}: {null_count} laps have null lap_time_ms",
        )
    ]


def check_implausible_times(
    df: pd.DataFrame,
    run_id: str,
    session_label: str,
    min_ms: int = 60_000,
    max_ms: int = 600_000,
) -> list[dict[str, Any]]:
    """Check for laps with times outside physically plausible bounds."""
    mask = df["lap_time_ms"].notna() & (
        (df["lap_time_ms"] < min_ms) | (df["lap_time_ms"] > max_ms)
    )
    count = int(mask.sum())
    severity = "WARNING" if count > 0 else "INFO"
    return [
        _row(
            run_id,
            "laps",
            "implausible_lap_times",
            severity,
            count,
            (
                f"session={session_label}: {count} laps outside [{min_ms},{max_ms}] ms"
                + (
                    f" – lap_nos: {df.loc[mask,'lap_no'].tolist()[:10]}"
                    if count > 0
                    else ""
                )
            ),
        )
    ]


def check_duplicate_stints(
    df: pd.DataFrame, run_id: str, session_label: str
) -> list[dict[str, Any]]:
    """
    Detect drivers with non-monotonic or duplicate stint numbers,
    which suggests a FastF1 stint-inference issue.
    """
    issues: list[str] = []
    if "stint" not in df.columns:
        return []
    for driver_id, grp in df.groupby("driver_id"):
        stints = grp.sort_values("lap_no")["stint"].dropna().astype(int)
        # Stint numbers should be monotonically non-decreasing
        if (stints.diff().dropna() < 0).any():
            issues.append(str(driver_id))
    count = len(issues)
    severity = "WARNING" if count > 0 else "INFO"
    return [
        _row(
            run_id,
            "laps",
            "duplicate_stints",
            severity,
            count,
            f"session={session_label}: {count} drivers with non-monotonic stint numbers"
            + (f" – driver_ids: {issues[:10]}" if issues else ""),
        )
    ]


def check_missing_laps(
    df: pd.DataFrame,
    run_id: str,
    session_label: str,
    expected_laps: int | None = None,
) -> list[dict[str, Any]]:
    """
    Check that each driver has a continuous sequence of lap numbers.
    Gaps (e.g. lap 5 missing between 4 and 6) are flagged.
    """
    issues: list[str] = []
    for driver_id, grp in df.groupby("driver_id"):
        lap_nos = sorted(grp["lap_no"].dropna().astype(int).tolist())
        if len(lap_nos) < 2:
            continue
        expected = list(range(lap_nos[0], lap_nos[-1] + 1))
        missing = set(expected) - set(lap_nos)
        if missing:
            issues.append(f"driver {driver_id}: missing laps {sorted(missing)[:5]}")
    count = len(issues)
    severity = "WARNING" if count > 0 else "INFO"
    return [
        _row(
            run_id,
            "laps",
            "missing_laps",
            severity,
            count,
            f"session={session_label}: {count} drivers with lap gaps"
            + (f" – {'; '.join(issues[:5])}" if issues else ""),
        )
    ]


def check_driver_number_mismatch(
    ff1_laps_df: pd.DataFrame,
    db_drivers_df: pd.DataFrame,
    run_id: str,
    session_label: str,
) -> list[dict[str, Any]]:
    """
    Compare driver codes present in FastF1 laps against the drivers table.
    Report any codes not found in the DB (they need to be inserted first).
    """
    ff1_codes = set(ff1_laps_df["Driver"].dropna().unique())
    db_codes = set(db_drivers_df["code"].str.upper().unique())
    missing = ff1_codes - db_codes
    count = len(missing)
    severity = "ERROR" if count > 0 else "INFO"
    return [
        _row(
            run_id,
            "drivers",
            "driver_number_mismatch",
            severity,
            count,
            f"session={session_label}: {count} FastF1 driver codes not in DB: {missing}",
        )
    ]


def check_session_load_failure(
    run_id: str, session_label: str, error: str
) -> list[dict[str, Any]]:
    """Log a session that failed to load from FastF1."""
    return [
        _row(
            run_id,
            "sessions",
            "session_load_failure",
            "ERROR",
            None,
            f"session={session_label}: FastF1 load failed – {error}",
        )
    ]


# ---------------------------------------------------------------------------
# Composite check runner
# ---------------------------------------------------------------------------


def run_all_lap_checks(
    df: pd.DataFrame,
    run_id: str,
    session_label: str,
) -> list[dict[str, Any]]:
    """Run all lap-level quality checks and return combined results."""
    checks = [
        check_null_lap_times,
        check_implausible_times,
        check_duplicate_stints,
        check_missing_laps,
    ]
    rows: list[dict[str, Any]] = []
    for fn in checks:
        try:
            rows.extend(fn(df, run_id, session_label))
        except Exception as exc:  # noqa: BLE001
            log.warning("DQ check %s failed: %s", fn.__name__, exc)
    return rows
