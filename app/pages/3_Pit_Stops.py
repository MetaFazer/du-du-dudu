"""
app/pages/3_Pit_Stops.py

Pit Stop Strategy page:
  • Pit lane delta per stop (ESTIMATED)  — bar chart + table
  • Stint strategy timeline (stacked bar by compound)
  • Undercut analysis (ESTIMATED) — success/fail pairs
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(
    page_title="Pit Stops · Du-Du-Du",
    page_icon="🔧",
    layout="wide",
)

from app.theme import (  # noqa: E402
    COLORS,
    TYRE_COLORS,
    apply_theme,
    estimated_badge,
    footer,
    inject_css,
    page_header,
)
from app.queries import (  # noqa: E402
    get_events,
    get_laps,
    get_pit_loss,
    get_pit_stops,
    get_sessions,
    get_undercut,
)

inject_css()
page_header("Pit Stop Analysis", "STRATEGY · DELTA · UNDERCUT")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
events = get_events(2025)
if events.empty:
    st.warning("No data yet.")
    st.stop()

events["label"] = events["round"].astype(str) + " · " + events["name"]
event_label = st.sidebar.selectbox("Round", events["label"].tolist(), key="pit_event")
ev_row = events[events["label"] == event_label].iloc[0]
event_id = int(ev_row["event_id"])
circuit = ev_row["circuit"]

sessions_df = get_sessions(event_id)
race_sess = sessions_df[sessions_df["type"].isin(["R", "Sprint"])]

if race_sess.empty:
    st.info(
        f"No race session loaded for **{ev_row['name']}**. "
        f"Run: `python -m etl.run --season 2025 --round {int(ev_row['round'])}`"
    )
    st.stop()

r_sid = int(race_sess.iloc[0]["session_id"])

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_delta, tab_strat, tab_undercut = st.tabs([
    "⏱ Pit Lane Delta (ESTIMATED)",
    "📊 Stint Strategy",
    "⚔️ Undercut Analysis (ESTIMATED)",
])

# ============================================================
# TAB 1: Pit Lane Delta
# ============================================================
with tab_delta:
    st.markdown(
        f"#### Estimated pit lane delta — {ev_row['name']} {estimated_badge()}",
        unsafe_allow_html=True,
    )
    st.markdown(
        "> **Method**: `(in-lap time + out-lap time) − 2 × driver's median clean lap`.\n"
        "> Includes tyre warm-up and any traffic on the out-lap. Fuel load change across stint not controlled.\n"
        "> **Do not use these numbers as absolute pit-lane durations — use `pit_lane_time_ms` for that.**"
    )

    pit_loss = get_pit_loss(r_sid)
    pit_stops = get_pit_stops(r_sid)

    if pit_loss.empty:
        st.info("No pit delta data. Views will populate after ETL runs for this round.")
    else:
        # Sort by driver
        pit_loss = pit_loss.sort_values(["code", "in_lap_no"])
        pit_loss["stop_label"] = (
            pit_loss["code"] + " Lap " + pit_loss["in_lap_no"].astype(str)
        )
        pit_loss["delta_s"] = pit_loss["pit_loss_ms_est"] / 1000

        fig = go.Figure()
        for code in pit_loss["code"].unique():
            sub = pit_loss[pit_loss["code"] == code]
            color = sub["color_hex"].iloc[0] or COLORS["muted"]
            fig.add_trace(go.Bar(
                name=code,
                x=sub["stop_label"],
                y=sub["delta_s"],
                marker_color=color,
                hovertemplate=(
                    f"<b>{code}</b><br>"
                    "Stop on lap %{customdata[0]}<br>"
                    "Δ (estimated): %{y:.2f}s<br>"
                    "Pit lane time: %{customdata[1]:.1f}s"
                    "<extra></extra>"
                ),
                customdata=list(zip(
                    sub["in_lap_no"],
                    (sub["pit_lane_time_ms"].fillna(0) / 1000).round(1),
                )),
            ))

        apply_theme(fig, f"{circuit} — Estimated Pit Lane Delta per Stop")
        fig.update_layout(
            height=420,
            xaxis_title="Driver · Stop lap",
            yaxis_title="Estimated delta (s) vs 2× median clean lap",
            xaxis_tickangle=-40,
            barmode="group",
            showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Table
        tbl = pit_loss[[
            "code", "full_name", "team_name",
            "in_lap_no", "out_lap_no",
            "pit_loss_ms_est", "pit_lane_time_ms",
            "ref_median_ms",
        ]].copy()
        tbl["pit_loss_ms_est"] = tbl["pit_loss_ms_est"].apply(
            lambda v: f"{v/1000:+.2f}s" if pd.notna(v) else "—"
        )
        tbl["pit_lane_time_ms"] = tbl["pit_lane_time_ms"].apply(
            lambda v: f"{v/1000:.1f}s" if pd.notna(v) else "—"
        )
        tbl["ref_median_ms"] = (tbl["ref_median_ms"] / 1000).round(3)
        tbl.columns = ["Code", "Driver", "Team", "In Lap", "Out Lap",
                       "Delta (est.)", "Pit Lane Time", "Ref Median (s)"]
        st.dataframe(tbl, hide_index=True, use_container_width=True)

    # Also show raw pit stop durations if available
    if not pit_stops.empty:
        st.markdown("---")
        st.markdown("#### Pit stop log (pit lane time from FastF1)")
        st.caption(
            "`pit_lane_time_ms` = PitOutTime − PitInTime from FastF1 timing. "
            "Null when the driver pit-in and pit-out occurred on different recorded laps."
        )
        raw_tbl = pit_stops[["code", "full_name", "team_name", "stop_no", "lap", "pit_lane_time_ms"]].copy()
        raw_tbl["pit_lane_time_ms"] = raw_tbl["pit_lane_time_ms"].apply(
            lambda v: f"{v/1000:.1f}s" if pd.notna(v) else "—"
        )
        raw_tbl.columns = ["Code", "Driver", "Team", "Stop #", "On Lap", "Pit Time"]
        st.dataframe(raw_tbl, hide_index=True, use_container_width=True)


# ============================================================
# TAB 2: Stint Strategy (stacked bar)
# ============================================================
with tab_strat:
    st.markdown(f"#### Stint length by compound — {ev_row['name']}")
    laps_df = get_laps(r_sid)

    if laps_df.empty:
        st.info("Lap data not loaded for this round.")
    else:
        # Compute stint lengths per driver
        stints = (
            laps_df.groupby(["code", "stint", "compound"])["lap_no"]
            .agg(["min", "max", "count"])
            .reset_index()
        )
        stints.columns = ["code", "stint", "compound", "lap_start", "lap_end", "laps"]
        stints = stints.sort_values(["code", "stint"])
        stints["compound"] = stints["compound"].fillna("UNKNOWN").str.upper()

        drivers = stints["code"].unique().tolist()
        fig = go.Figure()

        for compound in ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]:
            sub = stints[stints["compound"] == compound]
            if sub.empty:
                continue
            color = TYRE_COLORS.get(compound, COLORS["muted"])
            fig.add_trace(go.Bar(
                name=compound,
                x=sub["code"],
                y=sub["laps"],
                marker_color=color,
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    f"Compound: {compound}<br>"
                    "Stint length: %{y} laps<br>"
                    "Laps %{customdata[0]}–%{customdata[1]}<extra></extra>"
                ),
                customdata=list(zip(sub["lap_start"], sub["lap_end"])),
            ))

        apply_theme(fig, f"{circuit} — Stint Strategy (Laps by Compound)")
        fig.update_layout(
            barmode="stack",
            height=420,
            xaxis_title="Driver",
            yaxis_title="Laps",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Summary table
        stints_tbl = stints[["code", "stint", "compound", "lap_start", "lap_end", "laps"]].copy()
        stints_tbl.columns = ["Driver", "Stint", "Compound", "Lap Start", "Lap End", "Laps"]
        st.dataframe(stints_tbl, hide_index=True, use_container_width=True)


# ============================================================
# TAB 3: Undercut Analysis
# ============================================================
with tab_undercut:
    st.markdown(
        f"#### Undercut analysis — {ev_row['name']} {estimated_badge()}",
        unsafe_allow_html=True,
    )
    st.markdown(
        "> **Method**: Pairs of cars within ≤3 positions when one pits before the other (≤3 laps earlier). "
        "> Position comparison is made 2 laps after each driver's pit stop. "
        "> SC/VSC periods excluded. Position proximity used as gap proxy (telemetry not loaded yet). "
        "> **These are approximations** — use as research direction, not definitive strategy calls."
    )

    uc = get_undercut(r_sid)

    if uc.empty:
        st.info("No undercut data for this race. This view requires multiple pit-stopping pairs.")
    else:
        total = len(uc)
        success = uc["undercut_success"].sum()
        fail = total - success
        rate = round(100 * success / total, 1) if total else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Total undercut attempts", total)
        col2.metric("Successful", f"{success} ({rate}%)")
        col3.metric("Failed", fail)

        # Pie
        fig = go.Figure(go.Pie(
            values=[success, fail],
            labels=["Success", "Fail"],
            marker_colors=[COLORS["driver_a"], COLORS["accent"]],
            hole=0.5,
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        ))
        apply_theme(fig, f"{circuit} — Undercut Outcome (ESTIMATED)")
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)

        # Detail table
        st.markdown("#### All pairs")
        uc_tbl = uc[[
            "first_code", "second_code",
            "first_in_lap", "second_in_lap",
            "first_pos_before", "second_pos_before",
            "first_pos_after", "second_pos_after",
            "undercut_success",
        ]].copy()
        uc_tbl["undercut_success"] = uc_tbl["undercut_success"].map({True: "✅ Yes", False: "❌ No"})
        uc_tbl.columns = [
            "Pits First", "Pits Second",
            "First Pit Lap", "Second Pit Lap",
            "Pos Before (A)", "Pos Before (B)",
            "Pos After (A)", "Pos After (B)",
            "Success?",
        ]
        st.dataframe(uc_tbl, hide_index=True, use_container_width=True)

footer()
