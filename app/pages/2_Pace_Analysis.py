"""
app/pages/2_Pace_Analysis.py

Pace Analysis page:
  • Clean lap pace comparison — box plot / IQR bar per driver
  • Tyre degradation curve — delta from median vs tyre life, by compound
  • Teammate qualifying & race pace gap (bar chart + table)
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(
    page_title="Pace Analysis · Du-Du-Du",
    page_icon="📊",
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
    get_clean_lap_pace,
    get_events,
    get_laps,
    get_sessions,
    get_teammate_gap,
    get_tyre_deg,
)

inject_css()
page_header("Pace Analysis", "CLEAN PACE · TYRE DEG · TEAMMATES")

# ---------------------------------------------------------------------------
# Sidebar — event picker
# ---------------------------------------------------------------------------
events = get_events(2025)
if events.empty:
    st.warning("No data yet. Run the ETL pipeline first.")
    st.stop()

events["label"] = events["round"].astype(str) + " · " + events["name"]
event_label = st.sidebar.selectbox("Round", events["label"].tolist(), key="pace_event")
ev_row = events[events["label"] == event_label].iloc[0]
event_id = int(ev_row["event_id"])
circuit = ev_row["circuit"]

sessions_df = get_sessions(event_id)
race_sess = sessions_df[sessions_df["type"].isin(["R", "Sprint"])]
qual_sess = sessions_df[sessions_df["type"].isin(["Q", "SQ"])]

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_pace, tab_deg, tab_mates = st.tabs([
    "🏎 Clean Lap Pace",
    "📉 Tyre Degradation",
    "👥 Teammate Gap",
])

# ============================================================
# TAB 1: Clean lap pace
# ============================================================
with tab_pace:
    sess_opts = {}
    if not race_sess.empty:
        sess_opts["Race"] = int(race_sess.iloc[0]["session_id"])
    if not qual_sess.empty:
        sess_opts["Qualifying"] = int(qual_sess.iloc[0]["session_id"])

    if not sess_opts:
        st.info("No sessions loaded for this round.")
    else:
        chosen = st.radio("Session", list(sess_opts.keys()), horizontal=True, key="pace_sess")
        sid = sess_opts[chosen]

        pace_df = get_clean_lap_pace(sid)
        laps_df = get_laps(sid)

        if pace_df.empty:
            st.info("No clean-lap pace data for this session. Run ETL for this round first.")
        else:
            pace_df = pace_df.sort_values("median_ms")

            # IQR bar chart
            st.markdown(f"#### Median clean lap pace — {ev_row['name']} ({chosen})")
            st.caption(
                "Clean laps = is_clean flag (no yellow flags, no pit laps, implausible time filtered). "
                "Box = P25–P75. Line = median."
            )

            fig = go.Figure()
            for _, row in pace_df.iterrows():
                color = row.get("color_hex") or COLORS["muted"]
                med_s = row["median_ms"] / 1000
                p25_s = row["p25_ms"] / 1000
                p75_s = row["p75_ms"] / 1000
                best_s = row["best_ms"] / 1000 if pd.notna(row.get("best_ms")) else med_s

                fig.add_trace(go.Box(
                    name=row["code"],
                    q1=[p25_s],
                    median=[med_s],
                    q3=[p75_s],
                    lowerfence=[best_s],
                    upperfence=[p75_s + (p75_s - p25_s) * 1.5],
                    marker_color=color,
                    line_color=color,
                    fillcolor=f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.25)"
                    if color.startswith("#") else COLORS["panel"],
                    hovertemplate=(
                        f"<b>{row['code']}</b> — {row['team_name']}<br>"
                        f"Median: {med_s:.3f}s<br>"
                        f"Best: {best_s:.3f}s<br>"
                        f"Clean laps: {int(row['clean_lap_count'])}"
                        "<extra></extra>"
                    ),
                    boxpoints=False,
                ))
            apply_theme(fig, f"{circuit} — Clean Lap Pace ({chosen})")
            fig.update_layout(
                height=420,
                yaxis_title="Lap time (s)",
                xaxis_title="Driver",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Raw clean laps scatter (individual laps)
            if not laps_df.empty:
                st.markdown("#### Individual clean lap distribution")
                clean = laps_df[laps_df["is_clean"] == True].copy()  # noqa: E712
                if not clean.empty and clean["lap_time_ms"].notna().any():
                    clean["lap_time_s"] = clean["lap_time_ms"] / 1000
                    clean = clean.sort_values("lap_no")
                    fig2 = go.Figure()
                    for code in pace_df["code"].tolist():
                        sub = clean[clean["code"] == code]
                        if sub.empty:
                            continue
                        color = sub["color_hex"].iloc[0] or COLORS["muted"]
                        fig2.add_trace(go.Scatter(
                            x=sub["lap_no"],
                            y=sub["lap_time_s"],
                            mode="markers",
                            name=code,
                            marker=dict(color=color, size=5),
                            hovertemplate=f"<b>{code}</b> Lap %{{x}}: %{{y:.3f}}s<extra></extra>",
                        ))
                    apply_theme(fig2, f"{circuit} — Clean Laps ({chosen})")
                    fig2.update_layout(
                        height=350,
                        xaxis_title="Lap number",
                        yaxis_title="Lap time (s)",
                    )
                    st.plotly_chart(fig2, use_container_width=True)

            # Table
            st.markdown("#### Summary table")
            tbl = pace_df[["code", "full_name", "team_name", "clean_lap_count", "best_ms", "median_ms", "p25_ms", "p75_ms"]].copy()
            for col in ["best_ms", "median_ms", "p25_ms", "p75_ms"]:
                tbl[col] = (tbl[col] / 1000).round(3)
            tbl.columns = ["Code", "Driver", "Team", "Clean Laps", "Best (s)", "Median (s)", "P25 (s)", "P75 (s)"]
            st.dataframe(tbl, hide_index=True, use_container_width=True)

# ============================================================
# TAB 2: Tyre Degradation
# ============================================================
with tab_deg:
    st.markdown(f"#### Tyre degradation — {circuit}")
    st.markdown(
        f"> ⚠️ **Fuel effect not controlled.** Fuel burn (~0.03 s/lap/kg) improves lap time across a stint, "
        "partially masking tyre degradation. Delta is vs. each driver's own compound median for that session. "
        f"{estimated_badge()}",
        unsafe_allow_html=True,
    )

    deg_df = get_tyre_deg(circuit)

    if deg_df.empty:
        st.info("No tyre degradation data for this circuit yet. Multiple races needed to populate this chart.")
    else:
        compounds_avail = sorted(deg_df["compound"].unique())
        chosen_compounds = st.multiselect(
            "Compounds", compounds_avail, default=compounds_avail, key="deg_compounds"
        )
        deg_plot = deg_df[deg_df["compound"].isin(chosen_compounds)].copy()

        # Bucket by 5-lap windows and compute mean delta
        deg_plot["tyre_bucket"] = (deg_plot["tyre_life"] // 5) * 5
        agg = (
            deg_plot.groupby(["compound", "tyre_bucket"])["delta_from_median_ms"]
            .agg(["mean", "count"])
            .reset_index()
        )
        agg = agg[agg["count"] >= 3]  # min 3 laps per bucket
        agg["delta_s"] = agg["mean"] / 1000

        fig = go.Figure()
        for compound in chosen_compounds:
            sub = agg[agg["compound"] == compound].sort_values("tyre_bucket")
            if sub.empty:
                continue
            color = TYRE_COLORS.get(compound, COLORS["muted"])
            fig.add_trace(go.Scatter(
                x=sub["tyre_bucket"],
                y=sub["delta_s"],
                mode="lines+markers",
                name=compound,
                line=dict(color=color, width=2),
                marker=dict(color=color, size=7),
                hovertemplate=(
                    f"<b>{compound}</b><br>"
                    "Tyre age: %{x} laps (5-lap bucket)<br>"
                    "Avg Δ from median: %{y:.3f}s<extra></extra>"
                ),
            ))

        fig.add_hline(y=0, line_dash="dash", line_color=COLORS["panel_border"], line_width=1)
        apply_theme(fig, f"{circuit} — Tyre Δ vs Tyre Life (5-lap buckets, ESTIMATED)")
        fig.update_layout(
            height=400,
            xaxis_title="Tyre life (laps on set, 5-lap bucket)",
            yaxis_title="Δ vs driver's compound median (s)",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Slope table if enough data
        if len(deg_df) >= 20:
            st.markdown("#### Linear degradation slope (ESTIMATED)")
            st.caption("REGR_SLOPE(delta_ms, tyre_life) — positive = tyre getting slower per lap. Fuel effect uncontrolled.")
            from app.queries import _q
            slope_df = _q(
                """
                SELECT compound, COUNT(*) AS lap_count,
                       ROUND(REGR_SLOPE(delta_from_median_ms, tyre_life)::numeric, 2) AS slope_ms_per_lap,
                       ROUND(REGR_R2(delta_from_median_ms, tyre_life)::numeric, 4)   AS r_squared
                FROM mv_tyre_deg
                WHERE circuit = :c AND compound = ANY(:comps)
                GROUP BY compound
                HAVING COUNT(*) >= 10
                ORDER BY ABS(REGR_SLOPE(delta_from_median_ms, tyre_life)) DESC
                """,
                {"c": circuit, "comps": chosen_compounds},
            )
            if not slope_df.empty:
                slope_df.columns = ["Compound", "Laps", "Slope (ms/lap)", "R²"]
                st.dataframe(slope_df, hide_index=True, use_container_width=True)

# ============================================================
# TAB 3: Teammate Gap
# ============================================================
with tab_mates:
    st.markdown("#### Qualifying & race pace gap between teammates — 2025")
    st.caption(
        "Qualifying: best lap per driver per round. Race: median clean lap.\n"
        "Positive = Driver A faster than Driver B in that round.\n"
        "Driver A/B assignment is alphabetical by driver_id — no directional preference."
    )

    tg = get_teammate_gap(2025)

    if tg.empty:
        st.info("Teammate gap data not available yet — needs at least 1 race and qualifying loaded.")
    else:
        teams = sorted(tg["team_name"].unique())
        chosen_team = st.selectbox("Team", ["All"] + teams, key="tg_team")
        if chosen_team != "All":
            tg = tg[tg["team_name"] == chosen_team]

        # Qualifying gap chart
        tg_q = tg.dropna(subset=["q_gap_ms"]).copy()
        if not tg_q.empty:
            st.markdown("##### Qualifying gap (ms) — A minus B")
            tg_q["label"] = tg_q["team_name"] + " · " + tg_q["driver_a_code"] + " vs " + tg_q["driver_b_code"]
            fig = go.Figure(go.Bar(
                x=tg_q["label"],
                y=tg_q["q_gap_ms"],
                marker_color=[COLORS["driver_a"] if v <= 0 else COLORS["driver_b"] for v in tg_q["q_gap_ms"]],
                hovertemplate="<b>%{x}</b><br>Gap: %{y:.0f} ms<extra></extra>",
            ))
            fig.add_hline(y=0, line_color=COLORS["panel_border"])
            apply_theme(fig, "Qualifying Pace Gap (A – B) · Negative = A faster")
            fig.update_layout(height=350, xaxis_tickangle=-30, yaxis_title="Gap (ms)")
            st.plotly_chart(fig, use_container_width=True)

        # Race gap chart
        tg_r = tg.dropna(subset=["race_gap_ms"]).copy()
        if not tg_r.empty:
            st.markdown("##### Race gap — median clean lap (ms) — A minus B")
            tg_r["label"] = tg_r["team_name"] + " · " + tg_r["driver_a_code"] + " vs " + tg_r["driver_b_code"]
            fig2 = go.Figure(go.Bar(
                x=tg_r["label"],
                y=tg_r["race_gap_ms"],
                marker_color=[COLORS["driver_a"] if v <= 0 else COLORS["driver_b"] for v in tg_r["race_gap_ms"]],
                hovertemplate="<b>%{x}</b><br>Gap: %{y:.0f} ms<extra></extra>",
            ))
            fig2.add_hline(y=0, line_color=COLORS["panel_border"])
            apply_theme(fig2, "Race Pace Gap (A – B) · Negative = A faster")
            fig2.update_layout(height=350, xaxis_tickangle=-30, yaxis_title="Gap (ms)")
            st.plotly_chart(fig2, use_container_width=True)

        # Summary table
        tbl = tg[["team_name", "driver_a_code", "driver_b_code", "q_gap_ms", "race_gap_ms"]].copy()
        tbl["q_gap_ms"] = tbl["q_gap_ms"].round(0).astype("Int64")
        tbl["race_gap_ms"] = tbl["race_gap_ms"].round(0).astype("Int64")
        tbl.columns = ["Team", "Driver A", "Driver B", "Q Gap (ms)", "Race Gap (ms)"]
        st.dataframe(tbl, hide_index=True, use_container_width=True)

footer()
