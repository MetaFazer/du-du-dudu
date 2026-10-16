"""
tests/test_season.py – Unit tests for the season ETL orchestrator.

Tests cover sprint round detection, round filtering, and date skipping logic.
No DB connection required.
"""

from __future__ import annotations

from etl.season import SPRINT_ROUNDS_2025, _session_types_for_round


class TestSprintRoundDetection:
    def test_known_sprint_rounds_have_sq(self):
        """Every sprint round should include SQ and Sprint sessions."""
        for rnd in SPRINT_ROUNDS_2025:
            types = _session_types_for_round(rnd, 2025)
            assert "SQ" in types, f"Round {rnd} should have SQ"
            assert "Sprint" in types, f"Round {rnd} should have Sprint"

    def test_known_sprint_rounds_also_have_q_and_r(self):
        """Sprint weekends still have a standard Qualifying and Race."""
        for rnd in SPRINT_ROUNDS_2025:
            types = _session_types_for_round(rnd, 2025)
            assert "Q" in types
            assert "R" in types

    def test_normal_rounds_only_q_and_r(self):
        """Non-sprint rounds should return exactly ['Q', 'R']."""
        # Pick a round number that is definitely NOT a sprint
        non_sprint_rounds = [1, 2, 3, 4, 5, 7, 8, 9, 10]
        for rnd in non_sprint_rounds:
            types = _session_types_for_round(rnd, 2025)
            assert types == ["Q", "R"], f"Round {rnd} should be ['Q', 'R'], got {types}"

    def test_sprint_rounds_count(self):
        """2025 calendar has exactly 6 sprint weekends per the spec."""
        assert len(SPRINT_ROUNDS_2025) == 6

    def test_sprint_round_order(self):
        """Sprint sessions should come before Q in the return list."""
        for rnd in SPRINT_ROUNDS_2025:
            types = _session_types_for_round(rnd, 2025)
            sq_idx = types.index("SQ")
            q_idx  = types.index("Q")
            r_idx  = types.index("R")
            assert sq_idx < q_idx < r_idx, (
                f"Round {rnd}: expected SQ < Q < R, got {types}"
            )

    def test_other_season_returns_q_and_r(self):
        """For seasons other than 2025, sprint detection returns Q+R (safe default)."""
        # Our function only has sprint round data for 2025
        types = _session_types_for_round(6, 2024)  # round 6, but season 2024
        assert types == ["Q", "R"]
