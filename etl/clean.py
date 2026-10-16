"""
etl/clean.py – Lap cleaning and classification rules.

Every rule here must match what is documented in docs/methodology.md.
These are pure functions so they can be unit-tested without a DB or FastF1.
"""

from __future__ import annotations

import pandas as pd

# Track status codes that indicate a Safety Car or VSC period.
# FastF1 encodes status as a string like "2" or "4" on each lap.
# Reference: https://docs.fastf1.dev/lap_timing.html#track-status
SC_VSC_STATUS_CODES: frozenset[str] = frozenset({"2", "3", "4", "5", "6", "7"})
# Status 1 = Green, 2 = Yellow, 3 = SC deployed, 4 = VSC deployed,
# 5 = Red flag, 6 = VSC ending, 7 = Yellow virtual

# Tyre compounds that are not dry-weather slicks
WET_INTERMEDIATE_COMPOUNDS: frozenset[str] = frozenset({"WET", "INTERMEDIATE"})


def is_clean_lap(row: pd.Series) -> bool:
    """
    Return True if a lap qualifies as a 'clean' comparison lap.

    Rules (all must hold):
    1. Not an in-lap (pit_in_time is null).
    2. Not an out-lap (pit_out_time is null).
    3. Not lap 1 (formation / standing start anomalies).
    4. Not under Safety Car, Virtual Safety Car, or Red Flag
       (track_status does not contain any SC/VSC/RF code).
    5. Not on WET or INTERMEDIATE tyres.
    6. FastF1 marks the lap as accurate (IsAccurate == True).
    7. lap_time_ms is not null.

    This function takes a single row from the laps DataFrame.
    """
    # Rule 7 – lap time must exist
    if pd.isna(row.get("lap_time_ms")):
        return False

    # Rule 6 – FastF1 accuracy flag
    if not row.get("is_accurate", False):
        return False

    # Rule 3 – skip lap 1
    if row.get("lap_no", 0) <= 1:
        return False

    # Rule 1 – not an in-lap
    if not pd.isna(row.get("pit_in_time")):
        return False

    # Rule 2 – not an out-lap
    if not pd.isna(row.get("pit_out_time")):
        return False

    # Rule 4 – not under SC/VSC/RF
    track_status = str(row.get("track_status", "1"))
    for code in track_status:
        if code in SC_VSC_STATUS_CODES:
            return False

    # Rule 5 – dry-weather slick only
    compound = str(row.get("compound", "UNKNOWN")).upper()
    return compound not in WET_INTERMEDIATE_COMPOUNDS


def apply_clean_flag(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add or overwrite the 'is_clean' column on a laps DataFrame.

    The DataFrame must have columns:
        lap_time_ms, is_accurate, lap_no, pit_in_time, pit_out_time,
        track_status, compound

    Returns the same DataFrame with is_clean updated (does not copy).
    """
    df["is_clean"] = df.apply(is_clean_lap, axis=1)
    return df


def flag_implausible_times(
    df: pd.DataFrame,
    min_ms: int = 60_000,
    max_ms: int = 600_000,
) -> pd.DataFrame:
    """
    Mark laps with lap_time_ms outside [min_ms, max_ms] as not accurate.

    Default bounds:
        min_ms = 60 000 ms (60 s) — no F1 lap is shorter than 1 minute
        max_ms = 600 000 ms (10 min) — anything longer is clearly erroneous

    These are safety guards, not physical bounds; the DQ check in
    etl/quality.py reports them separately to dq_log.
    """
    mask = df["lap_time_ms"].notna() & (
        (df["lap_time_ms"] < min_ms) | (df["lap_time_ms"] > max_ms)
    )
    df.loc[mask, "is_accurate"] = False
    return df


def ms_to_timedelta(ms: float | None) -> pd.Timedelta | None:
    """Convert milliseconds to a pandas Timedelta. Returns None for null input."""
    if ms is None or pd.isna(ms):
        return None
    # Use explicit unit kwarg to avoid NumPy 'generic' Timedelta deprecation
    return pd.Timedelta(value=float(ms), unit="ms")


def timedelta_to_ms(td: pd.Timedelta | None) -> int | None:
    """Convert a pandas Timedelta to integer milliseconds. Returns None for null."""
    if td is None or pd.isna(td):
        return None
    return int(td.total_seconds() * 1000)
