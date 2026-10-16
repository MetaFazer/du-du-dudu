"""
tests/test_telemetry.py – Unit tests for Phase 4 Telemetry pipeline.

Tests pure functions in etl/telemetry.py with zero DB or FastF1 dependency:
  • resample_to_grid
  • compute_cumulative_time & compute_delta_time
  • compute_corner_distances
  • calculate_corner_stats
  • calculate_mini_sectors
  • generate_physics_telemetry
"""

import numpy as np
import pandas as pd
import pytest

from etl.telemetry import (
    calculate_corner_stats,
    calculate_mini_sectors,
    compute_corner_distances,
    compute_cumulative_time,
    compute_delta_time,
    generate_physics_telemetry,
    resample_to_grid,
)


def _make_sample_telemetry(total_dist: float = 1000.0) -> pd.DataFrame:
    """Helper creating a sample raw telemetry dataframe."""
    dist = np.linspace(0.0, total_dist, 50)
    speed = 100.0 + 50.0 * np.sin(dist / 100.0)
    throttle = np.clip(50.0 + 50.0 * np.cos(dist / 100.0), 0.0, 100.0)
    brake = throttle < 20.0
    gear = np.clip(np.round(speed / 30.0), 1, 8).astype(int)
    rpm = 10000 + (speed * 10).astype(int)
    drs = np.zeros(len(dist), dtype=int)
    x = dist * 0.5
    y = dist * 0.2

    return pd.DataFrame({
        "dist_m": dist,
        "speed": speed,
        "throttle": throttle,
        "brake": brake,
        "gear": gear,
        "rpm": rpm,
        "drs": drs,
        "x": x,
        "y": y,
    })


# ---------------------------------------------------------------------------
# 1. Resampling
# ---------------------------------------------------------------------------

def test_resample_to_grid_basic():
    raw = _make_sample_telemetry(500.0)
    res = resample_to_grid(raw, step_m=10.0, total_dist_m=500.0)

    assert not res.empty
    # Expect points at 0, 10, 20, ..., 500 -> 51 points
    assert len(res) == 51
    assert res["dist_m"].iloc[0] == 0.0
    assert res["dist_m"].iloc[-1] == 500.0
    assert (np.diff(res["dist_m"]) == 10.0).all()
    assert "speed" in res.columns
    assert "throttle" in res.columns
    assert "brake" in res.columns
    assert "gear" in res.columns


def test_resample_to_grid_empty():
    res = resample_to_grid(pd.DataFrame())
    assert res.empty


def test_resample_missing_dist_raises():
    with pytest.raises(ValueError, match="Telemetry DataFrame must contain"):
        resample_to_grid(pd.DataFrame({"speed": [100, 200]}))


# ---------------------------------------------------------------------------
# 2. Cumulative Time & Delta Time
# ---------------------------------------------------------------------------

def test_compute_cumulative_time_scaling():
    telem = pd.DataFrame({
        "dist_m": [0.0, 100.0, 200.0],
        "speed": [180.0, 180.0, 180.0],  # 180 km/h = 50 m/s -> 200m should take 4.0s
    })
    # Target official lap time 5000 ms (5.0s)
    t = compute_cumulative_time(telem, official_lap_time_ms=5000)
    assert len(t) == 3
    assert t[0] == 0.0
    assert pytest.approx(t[-1], 0.001) == 5.0


def test_compute_delta_time():
    t_a = pd.DataFrame({"dist_m": [0.0, 100.0, 200.0], "speed": [200.0, 200.0, 200.0]})
    t_b = pd.DataFrame({"dist_m": [0.0, 100.0, 200.0], "speed": [150.0, 150.0, 150.0]})

    delta = compute_delta_time(t_a, t_b, lap_time_a_ms=4000, lap_time_b_ms=5000)
    assert not delta.empty
    assert "delta_s" in delta.columns
    # Driver A was 4.0s total, Driver B was 5.0s total -> final delta should be -1.0s (A is faster)
    assert pytest.approx(delta["delta_s"].iloc[-1], 0.01) == -1.0


# ---------------------------------------------------------------------------
# 3. Corner Distances
# ---------------------------------------------------------------------------

def test_compute_corner_distances_fallback():
    corners_raw = pd.DataFrame({
        "Number": [1, 2, 3],
        "X": [0.0, 100.0, 200.0],
        "Y": [0.0, 50.0, 100.0],
        "Distance": [np.nan, np.nan, np.nan],
    })
    c = compute_corner_distances(corners_raw, total_dist_m=3000.0)
    assert len(c) == 3
    assert (c["corner_no"] == [1, 2, 3]).all()
    assert (np.diff(c["dist_m"]) > 0).all()


# ---------------------------------------------------------------------------
# 4. Corner Statistics
# ---------------------------------------------------------------------------

def test_calculate_corner_stats():
    # Construct synthetic telemetry with braking zone into corner at 300m
    dists = np.arange(0.0, 600.0, 10.0)
    speed = np.full(len(dists), 250.0)
    brake = np.zeros(len(dists), dtype=bool)
    throttle = np.full(len(dists), 100.0)

    # Corner apex at 300m
    # Braking window: 150m to 300m
    brake[(dists >= 180.0) & (dists <= 290.0)] = True
    throttle[(dists >= 180.0) & (dists <= 320.0)] = 0.0
    speed[(dists >= 250.0) & (dists <= 350.0)] = 110.0

    telem = pd.DataFrame({
        "dist_m": dists,
        "speed": speed,
        "brake": brake,
        "throttle": throttle,
    })
    corners = pd.DataFrame({
        "corner_no": [1],
        "dist_m": [300.0],
        "x": [10.0],
        "y": [20.0],
    })

    stats = calculate_corner_stats(telem, corners, session_id=1, driver_id=4, lap_no=15)
    assert len(stats) == 1
    s = stats[0]
    assert s["corner_no"] == 1
    # First brake point in [150, 300] is at 180m
    assert s["brake_point_m"] == 180.0
    # Minimum speed around apex is 110 km/h
    assert s["min_speed"] == 110.0
    # Throttle pickup after 300m happens at 330m
    assert s["throttle_pickup_m"] == 330.0


# ---------------------------------------------------------------------------
# 5. Mini-Sectors
# ---------------------------------------------------------------------------

def test_calculate_mini_sectors():
    dists = np.arange(0.0, 1000.0, 10.0)
    # Driver A is faster in first half, Driver B faster in second half
    spd_a = np.where(dists < 500.0, 250.0, 150.0)
    spd_b = np.where(dists < 500.0, 150.0, 250.0)

    df_a = pd.DataFrame({"dist_m": dists, "speed": spd_a})
    df_b = pd.DataFrame({"dist_m": dists, "speed": spd_b})

    mini = calculate_mini_sectors(
        telems={1: df_a, 2: df_b},
        driver_codes={1: "VER", 2: "HAM"},
        lap_times_ms={1: 60000, 2: 60000},
        n_segments=10,
    )
    assert len(mini) == 10
    # First sector winner should be VER
    assert mini.iloc[0]["winner_code"] == "VER"
    # Last sector winner should be HAM
    assert mini.iloc[-1]["winner_code"] == "HAM"


# ---------------------------------------------------------------------------
# 6. Physics Fallback Generator
# ---------------------------------------------------------------------------

def test_generate_physics_telemetry():
    corners = pd.DataFrame({
        "corner_no": [1, 2],
        "dist_m": [400.0, 800.0],
        "x": [100.0, 200.0],
        "y": [50.0, 150.0],
    })
    lap_ms = 75000  # 75.0s
    res = generate_physics_telemetry(
        total_dist_m=1200.0,
        lap_time_ms=lap_ms,
        s1_ms=25000,
        s2_ms=25000,
        s3_ms=25000,
        corners_df=corners,
        step_m=10.0,
    )

    assert not res.empty
    assert len(res) == 121  # 0 to 1200 at 10m steps
    assert res["dist_m"].iloc[0] == 0.0
    assert res["dist_m"].iloc[-1] == 1200.0
    assert res["speed"].min() >= 60.0
    assert res["speed"].max() <= 350.0
    assert (res["gear"] >= 1).all() and (res["gear"] <= 8).all()
    assert (res["rpm"] >= 9000).all()
    assert isinstance(res["brake"].iloc[0], bool | np.bool_)

    # Verify integrated time is close to official lap time
    cum_t = compute_cumulative_time(res, lap_ms)
    assert pytest.approx(cum_t[-1], 0.01) == 75.0
