"""
tests/test_clean.py – Unit tests for lap cleaning rules in etl/clean.py.

These tests use synthetic DataFrames; no DB, no FastF1 required.
"""

from __future__ import annotations

import pandas as pd
import pytest

from etl.clean import (
    apply_clean_flag,
    flag_implausible_times,
    is_clean_lap,
    ms_to_timedelta,
    timedelta_to_ms,
)

# ---------------------------------------------------------------------------
# Helpers to build synthetic lap rows
# ---------------------------------------------------------------------------


def make_lap(**overrides) -> pd.Series:
    """Return a Series representing a clean baseline lap, with optional overrides."""
    base = {
        "lap_time_ms": 90_000,     # 1 min 30 s – plausible
        "is_accurate": True,
        "lap_no": 10,
        "pit_in_time": None,       # not an in-lap
        "pit_out_time": None,      # not an out-lap
        "track_status": "1",       # green flag
        "compound": "SOFT",
    }
    base.update(overrides)
    return pd.Series(base)


# ---------------------------------------------------------------------------
# is_clean_lap
# ---------------------------------------------------------------------------


class TestIsCleanLap:
    def test_clean_baseline(self):
        assert is_clean_lap(make_lap()) is True

    def test_null_lap_time(self):
        assert is_clean_lap(make_lap(lap_time_ms=None)) is False

    def test_not_accurate(self):
        assert is_clean_lap(make_lap(is_accurate=False)) is False

    def test_lap_one(self):
        assert is_clean_lap(make_lap(lap_no=1)) is False

    def test_lap_zero(self):
        assert is_clean_lap(make_lap(lap_no=0)) is False

    def test_in_lap(self):
        # pit_in_time is not None → in-lap
        assert is_clean_lap(make_lap(pit_in_time=1_234_567)) is False

    def test_out_lap(self):
        assert is_clean_lap(make_lap(pit_out_time=987_654)) is False

    @pytest.mark.parametrize("status", ["2", "3", "4", "5", "6", "7"])
    def test_sc_vsc_red_statuses(self, status):
        assert is_clean_lap(make_lap(track_status=status)) is False

    def test_mixed_status_with_sc(self):
        # "14" contains '4' (VSC) so should be excluded
        assert is_clean_lap(make_lap(track_status="14")) is False

    def test_green_flag_allowed(self):
        assert is_clean_lap(make_lap(track_status="1")) is True

    @pytest.mark.parametrize("compound", ["WET", "INTERMEDIATE", "wet", "intermediate"])
    def test_wet_intermediate_compounds(self, compound):
        assert is_clean_lap(make_lap(compound=compound)) is False

    @pytest.mark.parametrize("compound", ["SOFT", "MEDIUM", "HARD", "UNKNOWN"])
    def test_dry_compounds_allowed(self, compound):
        assert is_clean_lap(make_lap(compound=compound)) is True

    def test_lap_two_is_allowed(self):
        # Lap 2 is fine – only lap 1 is excluded
        assert is_clean_lap(make_lap(lap_no=2)) is True


# ---------------------------------------------------------------------------
# apply_clean_flag
# ---------------------------------------------------------------------------


class TestApplyCleanFlag:
    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        series = [make_lap(**r) for r in rows]
        return pd.DataFrame(series)

    def test_all_clean(self):
        df = self._make_df([{}, {}, {}])
        result = apply_clean_flag(df)
        assert result["is_clean"].all()

    def test_lap_one_not_clean(self):
        df = self._make_df([{"lap_no": 1}, {"lap_no": 5}])
        result = apply_clean_flag(df)
        # Use == not 'is' — pandas returns np.bool_ scalars, not Python bool
        assert result.iloc[0]["is_clean"] == False  # noqa: E712
        assert result.iloc[1]["is_clean"] == True   # noqa: E712

    def test_null_time_not_clean(self):
        df = self._make_df([{"lap_time_ms": None}, {}])
        result = apply_clean_flag(df)
        assert result.iloc[0]["is_clean"] == False  # noqa: E712
        assert result.iloc[1]["is_clean"] == True   # noqa: E712

    def test_sc_lap_not_clean(self):
        df = self._make_df([{"track_status": "4"}, {}])
        result = apply_clean_flag(df)
        assert result.iloc[0]["is_clean"] == False  # noqa: E712
        assert result.iloc[1]["is_clean"] == True   # noqa: E712

    def test_in_lap_not_clean(self):
        df = self._make_df([{"pit_in_time": 50_000}, {}])
        result = apply_clean_flag(df)
        assert result.iloc[0]["is_clean"] == False  # noqa: E712

    def test_out_lap_not_clean(self):
        df = self._make_df([{"pit_out_time": 50_000}, {}])
        result = apply_clean_flag(df)
        assert result.iloc[0]["is_clean"] == False  # noqa: E712


# ---------------------------------------------------------------------------
# flag_implausible_times
# ---------------------------------------------------------------------------


class TestFlagImplausibleTimes:
    def _make_df(self, times: list[int | None]) -> pd.DataFrame:
        rows = []
        for t in times:
            row = make_lap(lap_time_ms=t)
            rows.append(row)
        df = pd.DataFrame(rows)
        return df

    def test_plausible_times_unchanged(self):
        df = self._make_df([90_000, 95_000, 88_000])
        result = flag_implausible_times(df)
        assert result["is_accurate"].all()

    def test_too_short_flagged(self):
        df = self._make_df([59_999, 90_000])
        result = flag_implausible_times(df)
        assert result.iloc[0]["is_accurate"] == False  # noqa: E712
        assert result.iloc[1]["is_accurate"] == True   # noqa: E712

    def test_too_long_flagged(self):
        df = self._make_df([90_000, 600_001])
        result = flag_implausible_times(df)
        assert result.iloc[0]["is_accurate"] == True   # noqa: E712
        assert result.iloc[1]["is_accurate"] == False  # noqa: E712

    def test_null_time_not_flagged(self):
        # Null times don't get the is_accurate=False treatment here —
        # they just remain as-is (null_lap_times DQ check covers them)
        df = self._make_df([None])
        result = flag_implausible_times(df)
        # is_accurate should stay True (only implausible non-null times get flagged)
        assert result.iloc[0]["is_accurate"] == True   # noqa: E712

    def test_custom_bounds(self):
        df = self._make_df([70_000, 90_000])
        result = flag_implausible_times(df, min_ms=80_000, max_ms=100_000)
        assert result.iloc[0]["is_accurate"] == False  # noqa: E712
        assert result.iloc[1]["is_accurate"] == True   # noqa: E712


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_ms_to_timedelta_valid(self):
        td = ms_to_timedelta(90_000)
        # Use unit='s' to avoid NumPy generic Timedelta deprecation warning
        assert td == pd.Timedelta(value=90, unit="s")

    def test_ms_to_timedelta_none(self):
        assert ms_to_timedelta(None) is None

    def test_timedelta_to_ms_valid(self):
        td = pd.Timedelta(value=90, unit="s")
        assert timedelta_to_ms(td) == 90_000

    def test_timedelta_to_ms_none(self):
        assert timedelta_to_ms(None) is None

    def test_roundtrip(self):
        original_ms = 91_234
        td = ms_to_timedelta(original_ms)
        result = timedelta_to_ms(td)
        assert result == original_ms
