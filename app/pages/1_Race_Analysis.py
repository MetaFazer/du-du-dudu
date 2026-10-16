"""
app/pages/1_Race_Analysis.py

Race Analysis page:
  • Results table (qualifying + race) with positions and status
  • Grid vs. Finish — bar chart of places gained/lost
  • Stint strategy — lap-by-lap compound chart
  • Safety car / VSC windows overlaid on the stint chart
  • Reliability summary (DNF counts by team)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---- must be first Streamlit call ----
st.set_page_config(
    page_title="Race Analysis · Du-Du-Dudu",
    page_icon="🏁",
    layout="wide",
)

from app.queries import (  # noqa: E402
    get_events,
    get_grid_vs_finish,
    get_laps,
    get_race_control,
    get_reliability,
    get_results,
    get_sessions,
)
from app.theme import (  # noqa: E402
    COLORS,
    TYRE_COLORS,
    apply_theme,
    footer,
    inject_css,
    page_header,
)

inject_css()
page_header("Race Analysis", "RACE · GRID · STINTS")

# ---------------------------------------------------------------------------
# Sidebar – event / session picker
# ---------------------------------------------------------------------------
events = get_events(2025)

if events.empty:
    st.warning("No race data in the database yet. Run the ETL pipeline first.")
    st.stop()

events["label"] = events["round"].astype(str) + " · " + events["name"]
event_label = st.sidebar.selectbox("Round", events["label"].tolist(), key="race_event")
ev_row = events[events["label"] == event_label].iloc[0]
event_id = int(ev_row["event_id"])
circuit = ev_row["circuit"]

sessions_df = get_sessions(event_id)
race_sessions = sessions_df[sessions_df["type"].isin(["R", "Sprint"])]
qual_sessions = sessions_df[sessions_df["type"].isin(["Q", "SQ"])]

if race_sessions.empty:
    st.info(f"No race session loaded yet for **{ev_row['name']}**. Run: `python -m etl.run --season 2025 --round {ev_row['round']}`")
    st.stop()

r_sid = int(race_sessions.iloc[0]["session_id"])
q_sid = int(qual_sessions.iloc[0]["session_id"]) if not qual_sessions.empty else None

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------
tab_race, tab_stints, tab_reliability = st.tabs(["🏆 Results & Positions", "🔄 Stint Strategy", "🔧 Reliability"])

# ============================================================
# TAB 1: Results + Grid vs Finish
# ============================================================
with tab_race:
    col_q, col_r = st.columns(2)

    # Qualifying table
    with col_q:
        st.markdown("#### Qualifying")
        if q_sid:
            q_results = get_results(q_sid)
            if not q_results.empty:
                q_display = q_results[["position", "code", "full_name", "team_name"]].copy()
                q_display.columns = ["Pos", "Code", "Driver", "Team"]
                q_display["Pos"] = q_display["Pos"].fillna("—")
                st.dataframe(
                    q_display,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Pos": st.column_config.TextColumn("Pos", width=40),
                        "Code": st.column_config.TextColumn("Code", width=50),
                    },
                )
            else:
                st.caption("No qualifying data.")
        else:
            st.caption("No qualifying session.")

    # Race table
    with col_r:
        st.markdown("#### Race")
        r_results = get_results(r_sid)
        if not r_results.empty:
            r_display = r_results[["position", "code", "full_name", "team_name", "points", "status"]].copy()
            r_display.columns = ["Pos", "Code", "Driver", "Team", "Pts", "Status"]
            r_display["Pos"] = r_display["Pos"].fillna("—")
            r_display["Pts"] = r_display["Pts"].apply(lambda x: str(int(x)) if pd.notna(x) and x > 0 else "—")
            st.dataframe(
                r_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Pos": st.column_config.TextColumn("Pos", width=40),
                    "Code": st.column_config.TextColumn("Code", width=50),
                    "Pts": st.column_config.TextColumn("Pts", width=40),
                },
            )
        else:
            st.caption("No race result data.")

    st.markdown("---")

    # Grid vs Finish chart
    st.markdown("#### Grid → Finish: positions gained/lost")
    gvf = get_grid_vs_finish(r_sid)

    if not gvf.empty and "places_gained" in gvf.columns:
        gvf_plot = gvf.dropna(subset=["places_gained"]).copy()
        gvf_plot = gvf_plot.sort_values("places_gained", ascending=True)

        bar_colors = [
            COLORS["accent"] if v < 0 else COLORS["driver_a"] if v > 0 else COLORS["muted"]
            for v in gvf_plot["places_gained"]
        ]
        hover = [
            f"<b>{row['code']}</b><br>{row['full_name']}<br>{row['team_name']}<br>"
            f"Grid: {row['grid']} → P{row['position']}<br>Gained: {'+' if row['places_gained'] > 0 else ''}{int(row['places_gained'])}"
            for _, row in gvf_plot.iterrows()
        ]

        fig = go.Figure(go.Bar(
            x=gvf_plot["code"],
            y=gvf_plot["places_gained"],
            marker_color=bar_colors,
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
        ))
        fig.add_hline(y=0, line_color=COLORS["panel_border"], line_width=1)
        apply_theme(fig, f"{circuit} — Places Gained/Lost")
        fig.update_layout(
            yaxis_title="Places Gained (positive = forward)",
            xaxis_title="Driver",
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        # DNF list
        dnfs = gvf[gvf["is_dnf"] == True]  # noqa: E712
        if not dnfs.empty:
            st.markdown("**DNFs this race**")
            dnf_display = dnfs[["code", "full_name", "team_name", "status"]].copy()
            dnf_display.columns = ["Code", "Driver", "Team", "Status"]
            st.dataframe(dnf_display, hide_index=True, use_container_width=True)
    else:
        st.caption("Grid vs finish data not available (run ETL to populate results).")

# ============================================================
# TAB 2: Stint Strategy
# ============================================================
with tab_stints:
    laps = get_laps(r_sid)
    rc = get_race_control(r_sid)

    if laps.empty:
        st.info("Lap data not loaded yet for this race.")
    else:
        # Build stint chart: each driver row, coloured by compound per lap
        drivers_in_race = sorted(laps["code"].unique())
        driver_order = st.sidebar.multiselect(
            "Drivers to show",
            options=drivers_in_race,
            default=drivers_in_race[:10],
            key="stint_drivers",
        )
        laps_plot = laps[laps["code"].isin(driver_order)].copy()

        fig = go.Figure()

        # SC/VSC shaded regions
        if not rc.empty:
            sc_on_lap: int | None = None
            for _, msg in rc.iterrows():
                lap = msg.get("lap")
                flag = str(msg.get("flag", "") or "")
                message = str(msg.get("message", "") or "")
                is_sc = "SC" in flag or "safety car" in message.lower()
                is_vsc = "VSC" in flag or "virtual safety car" in message.lower()
                is_clear = "all clear" in message.lower() or flag == "GREEN"

                if (is_sc or is_vsc) and lap and sc_on_lap is None:
                    sc_on_lap = int(lap)
                    sc_label = "SC" if is_sc else "VSC"
                elif is_clear and sc_on_lap is not None and lap:
                    fig.add_vrect(
                        x0=sc_on_lap - 0.5, x1=int(lap) + 0.5,
                        fillcolor=COLORS["warning"], opacity=0.07,
                        layer="below", line_width=0,
                        annotation_text=sc_label, annotation_font_color=COLORS["warning"],
                        annotation_font_size=9,
                    )
                    sc_on_lap = None

        # Compound traces per driver
        for code in driver_order:
            drv = laps_plot[laps_plot["code"] == code].sort_values("lap_no")
            for compound in drv["compound"].dropna().unique():
                sub = drv[drv["compound"] == compound]
                color = TYRE_COLORS.get(str(compound).upper(), COLORS["muted"])
                fig.add_trace(go.Scatter(
                    x=sub["lap_no"],
                    y=[code] * len(sub),
                    mode="markers",
                    marker={"color": color, "size": 10, "symbol": "square"},
                    name=f"{code} – {compound}",
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{code}</b> Lap %{{x}}<br>"
                        f"Compound: {compound}<extra></extra>"
                    ),
                ))

        # Compound legend
        for compound, color in TYRE_COLORS.items():
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers",
                marker={"color": color, "size": 10, "symbol": "square"},
                name=compound,
            ))

        apply_theme(fig, f"{circuit} — Tyre Strategy by Driver")
        fig.update_layout(
            height=max(350, len(driver_order) * 30 + 100),
            xaxis_title="Lap",
            yaxis_title="Driver",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Clean lap time scatter
        st.markdown("#### Clean lap times")
        clean = laps_plot[laps_plot["is_clean"] == True].copy()  # noqa: E712
        if not clean.empty and clean["lap_time_ms"].notna().any():
            clean["lap_time_s"] = clean["lap_time_ms"] / 1000
            fig2 = go.Figure()
            for code in driver_order:
                sub = clean[clean["code"] == code]
                if sub.empty:
                    continue
                color_hex = sub["color_hex"].iloc[0] if "color_hex" in sub.columns else COLORS["muted"]
                fig2.add_trace(go.Scatter(
                    x=sub["lap_no"], y=sub["lap_time_s"],
                    mode="markers",
                    name=code,
                    marker={"color": color_hex or COLORS["muted"], "size": 5},
                    hovertemplate=f"<b>{code}</b> Lap %{{x}}: %{{y:.3f}}s<extra></extra>",
                ))
            apply_theme(fig2, f"{circuit} — Clean Lap Times (Race)")
            fig2.update_layout(height=350, xaxis_title="Lap", yaxis_title="Lap time (s)")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.caption("No clean laps flagged for this session yet.")

# ============================================================
# TAB 3: Reliability
# ============================================================
with tab_reliability:
    rel = get_reliability(2025)
    if rel.empty:
        st.info("Reliability data not available yet — needs multiple races loaded.")
    else:
        st.markdown("#### DNF count by team · 2025 season")
        st.caption("'Mechanical' excludes accidents/collisions per status string matching.")

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Mechanical DNF",
            x=rel["team_name"],
            y=rel["mechanical_dnf_count"],
            marker_color=COLORS["accent"],
        ))
        fig.add_trace(go.Bar(
            name="Incident DNF",
            x=rel["team_name"],
            y=rel["incident_dnf_count"],
            marker_color=COLORS["warning"],
        ))
        apply_theme(fig, "2025 DNFs by Team")
        fig.update_layout(
            barmode="stack",
            height=380,
            xaxis_tickangle=-35,
            yaxis_title="DNF Count",
        )
        st.plotly_chart(fig, use_container_width=True)

        rel_display = rel[["team_name", "total_races", "dnf_count", "mechanical_dnf_count", "incident_dnf_count", "dnf_pct"]].copy()
        rel_display.columns = ["Team", "Races", "DNFs", "Mechanical", "Incident", "DNF %"]
        st.dataframe(rel_display, hide_index=True, use_container_width=True)

footer()
