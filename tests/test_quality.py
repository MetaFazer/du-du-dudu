"""
tests/test_quality.py – Unit tests for DQ checks in etl/quality.py.

All checks operate on synthetic DataFrames; no DB, no FastF1 required.
"""

from __future__ import annotations

import pandas as pd

from etl.quality import (
    check_duplicate_stints,
    check_implausible_times,
    check_missing_laps,
    check_null_lap_times,
    check_session_load_failure,
    run_all_lap_checks,
)

RUN_ID = "test-run-001"
LABEL = "2025 R1 R"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _laps(**col_overrides) -> pd.DataFrame:
    """Return a minimal laps DataFrame with sensible defaults."""
    base = {
        "driver_id": [1, 1, 1, 2, 2, 2],
        "lap_no":    [2, 3, 4, 2, 3, 4],
        "lap_time_ms": [90_000, 91_000, 90_500, 89_000, 90_100, 90_300],
        "stint": [1, 1, 1, 1, 1, 1],
    }
    base.update(col_overrides)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# check_null_lap_times
# ---------------------------------------------------------------------------


class TestNullLapTimes:
    def test_no_nulls_is_info(self):
        df = _laps()
        rows = check_null_lap_times(df, RUN_ID, LABEL)
        assert len(rows) == 1
        assert rows[0]["severity"] == "INFO"
        assert rows[0]["row_count"] == 0

    def test_some_nulls_is_warning(self):
        df = _laps(lap_time_ms=[None, 90_000, 91_000, 90_000, 90_000, 90_000])
        rows = check_null_lap_times(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 1

    def test_all_nulls_is_warning(self):
        df = _laps(lap_time_ms=[None] * 6)
        rows = check_null_lap_times(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 6


# ---------------------------------------------------------------------------
# check_implausible_times
# ---------------------------------------------------------------------------


class TestImplausibleTimes:
    def test_all_plausible_is_info(self):
        df = _laps()
        rows = check_implausible_times(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "INFO"
        assert rows[0]["row_count"] == 0

    def test_too_short_flagged(self):
        df = _laps(lap_time_ms=[59_999, 90_000, 90_000, 90_000, 90_000, 90_000])
        rows = check_implausible_times(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 1

    def test_too_long_flagged(self):
        df = _laps(lap_time_ms=[90_000, 90_000, 600_001, 90_000, 90_000, 90_000])
        rows = check_implausible_times(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 1

    def test_null_times_not_counted(self):
        # Null lap times are not "implausible" — they're a separate check
        df = _laps(lap_time_ms=[None, 90_000, 90_000, 90_000, 90_000, 90_000])
        rows = check_implausible_times(df, RUN_ID, LABEL)
        assert rows[0]["row_count"] == 0


# ---------------------------------------------------------------------------
# check_duplicate_stints
# ---------------------------------------------------------------------------


class TestDuplicateStints:
    def test_monotonic_stints_ok(self):
        df = _laps(
            driver_id=[1, 1, 1, 1],
            lap_no=[2, 3, 4, 5],
            lap_time_ms=[90_000] * 4,
            stint=[1, 1, 2, 2],
        )
        rows = check_duplicate_stints(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "INFO"
        assert rows[0]["row_count"] == 0

    def test_non_monotonic_stint_flagged(self):
        # Stint goes 1 -> 2 -> 1 — invalid
        df = _laps(
            driver_id=[1, 1, 1],
            lap_no=[2, 3, 4],
            lap_time_ms=[90_000, 90_000, 90_000],
            stint=[1, 2, 1],
        )
        rows = check_duplicate_stints(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 1

    def test_missing_stint_column_returns_empty(self):
        df = _laps().drop(columns=["stint"])
        rows = check_duplicate_stints(df, RUN_ID, LABEL)
        assert rows == []


# ---------------------------------------------------------------------------
# check_missing_laps
# ---------------------------------------------------------------------------


class TestMissingLaps:
    def test_no_gaps_ok(self):
        df = _laps()
        rows = check_missing_laps(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "INFO"
        assert rows[0]["row_count"] == 0

    def test_gap_flagged(self):
        # Driver 1 has laps 2, 3, 5 — lap 4 is missing
        df = _laps(
            driver_id=[1, 1, 1, 2, 2, 2],
            lap_no=[2, 3, 5, 2, 3, 4],
            lap_time_ms=[90_000] * 6,
            stint=[1] * 6,
        )
        rows = check_missing_laps(df, RUN_ID, LABEL)
        assert rows[0]["severity"] == "WARNING"
        assert rows[0]["row_count"] == 1  # 1 driver with gaps

    def test_single_lap_driver_ignored(self):
        # A driver with only one lap can't have gaps
        df = _laps(
            driver_id=[1],
            lap_no=[5],
            lap_time_ms=[90_000],
            stint=[1],
        )
        rows = check_missing_laps(df, RUN_ID, LABEL)
        assert rows[0]["row_count"] == 0


# ---------------------------------------------------------------------------
# check_session_load_failure
# ---------------------------------------------------------------------------


class TestSessionLoadFailure:
    def test_returns_error_row(self):
        rows = check_session_load_failure(RUN_ID, LABEL, "timeout")
        assert len(rows) == 1
        assert rows[0]["severity"] == "ERROR"
        assert rows[0]["check_name"] == "session_load_failure"
        assert "timeout" in rows[0]["detail"]

    def test_correct_table_name(self):
        rows = check_session_load_failure(RUN_ID, LABEL, "some error")
        assert rows[0]["table_name"] == "sessions"


# ---------------------------------------------------------------------------
# run_all_lap_checks
# ---------------------------------------------------------------------------


class TestRunAllLapChecks:
    def test_returns_four_check_rows(self):
        df = _laps()
        rows = run_all_lap_checks(df, RUN_ID, LABEL)
        # We expect 4 checks: null_lap_times, implausible_times,
        # duplicate_stints, missing_laps
        check_names = {r["check_name"] for r in rows}
        assert "null_lap_times" in check_names
        assert "implausible_lap_times" in check_names
        assert "duplicate_stints" in check_names
        assert "missing_laps" in check_names

    def test_run_id_propagated(self):
        df = _laps()
        rows = run_all_lap_checks(df, RUN_ID, LABEL)
        assert all(r["run_id"] == RUN_ID for r in rows)

    def test_clean_data_all_info(self):
        df = _laps()
        rows = run_all_lap_checks(df, RUN_ID, LABEL)
        severities = {r["severity"] for r in rows}
        # All clean data should produce only INFO
        assert severities == {"INFO"}
