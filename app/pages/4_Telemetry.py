"""
app/pages/4_Telemetry.py

Driver Telemetry page:
  • Fastest lap comparison between two drivers on a 10m resampled grid
  • Speed vs. Distance comparison with circuit corner markers
  • Delta time trace (integrated time difference, scaled to official lap time)
  • Throttle, brake, gear, and RPM pedal inputs
  • 25 Mini-sectors dominance breakdown
  • Corner-by-corner analysis table (braking point, apex min speed, throttle pickup, exit speed)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ---- must be first Streamlit call ----
st.set_page_config(
    page_title="Driver Telemetry · Du-Du-Dudu",
    page_icon="⚡",
    layout="wide",
)

from app.queries import (  # noqa: E402
    get_circuit_corners,
    get_corner_stats,
    get_events,
    get_lap_telemetry,
    get_sessions,
    get_telemetry_drivers,
)
from app.theme import (  # noqa: E402
    COLORS,
    apply_theme,
    driver_card,
    estimated_badge,
    footer,
    inject_css,
    page_header,
)
from etl.telemetry import calculate_mini_sectors, compute_delta_time  # noqa: E402

inject_css()
page_header("Driver Telemetry", "10M GRID · DELTA · CORNERS")

# ---------------------------------------------------------------------------
# Sidebar – event / session / driver pickers
# ---------------------------------------------------------------------------
events = get_events(2025)

if events.empty:
    st.warning("No race data in the database yet. Run the ETL pipeline first.")
    st.stop()

events["label"] = events["round"].astype(str) + " · " + events["name"]
event_label = st.sidebar.selectbox("Round", events["label"].tolist(), key="telem_event")
ev_row = events[events["label"] == event_label].iloc[0]
event_id = int(ev_row["event_id"])
circuit = ev_row["circuit"]

sessions_df = get_sessions(event_id)
if sessions_df.empty:
    st.info("No sessions found for this event.")
    st.stop()

# Order sessions Q -> R -> Sprint -> SQ
s_order = {"Q": 1, "R": 2, "Sprint": 3, "SQ": 4}
sessions_df["ord"] = sessions_df["type"].map(lambda t: s_order.get(t, 9))
sessions_df = sessions_df.sort_values("ord")

session_type = st.sidebar.selectbox(
    "Session",
    sessions_df["type"].tolist(),
    index=0,
    key="telem_session_type",
)
session_id = int(sessions_df[sessions_df["type"] == session_type]["session_id"].iloc[0])

# Fetch available drivers who have telemetry loaded
telem_drivers = get_telemetry_drivers(session_id)

if telem_drivers.empty:
    st.warning(
        f"No telemetry loaded for {session_type} yet. "
        f"Run `python -m etl.run --season 2025 --round {ev_row['round']} --telemetry` to populate."
    )
    st.stop()

# Helper for formatting ms -> M:SS.sss
def fmt_lap(ms: int | float | None) -> str:
    if ms is None or np.isnan(ms) or ms <= 0:
        return "—"
    m = int(ms // 60000)
    s = (ms % 60000) / 1000.0
    return f"{m}:{s:06.3f}" if m > 0 else f"{s:.3f}s"

def fmt_sec(ms: int | float | None) -> str:
    if ms is None or np.isnan(ms) or ms <= 0:
        return "—"
    return f"{ms/1000.0:.3f}s"

# Driver selections
driver_codes = telem_drivers["code"].tolist()
driver_id_map = dict(zip(telem_drivers["code"], telem_drivers["driver_id"], strict=False))

col_da, col_db = st.sidebar.columns(2)
with col_da:
    driver_a_code = st.selectbox("Driver A", driver_codes, index=0, key="driver_a")
with col_db:
    default_b = 1 if len(driver_codes) > 1 else 0
    driver_b_code = st.selectbox("Driver B", driver_codes, index=default_b, key="driver_b")

driver_a_id = driver_id_map[driver_a_code]
driver_b_id = driver_id_map[driver_b_code]

# Load telemetry DataFrames
tel_a = get_lap_telemetry(session_id, driver_a_id)
tel_b = get_lap_telemetry(session_id, driver_b_id)
corners_df = get_circuit_corners(session_id)

row_a = telem_drivers[telem_drivers["driver_id"] == driver_a_id].iloc[0]
row_b = telem_drivers[telem_drivers["driver_id"] == driver_b_id].iloc[0]

color_a = row_a["color_hex"] or COLORS["accent"]
color_b = row_b["color_hex"] or COLORS["warning"]
if color_a == color_b:
    color_b = COLORS["driver_b"]

# ---------------------------------------------------------------------------
# Driver Summary Header Cards
# ---------------------------------------------------------------------------
top_spd_a = f"{tel_a['speed'].max():.1f} km/h" if not tel_a.empty else "—"
top_spd_b = f"{tel_b['speed'].max():.1f} km/h" if not tel_b.empty else "—"

card_col_1, card_col_2 = st.columns(2)
with card_col_1:
    st.markdown(
        driver_card(
            code=f"{row_a['code']} · {row_a['full_name']}",
            lap_time=fmt_lap(row_a["lap_time_ms"]),
            s1=fmt_sec(row_a["s1_ms"]),
            s2=fmt_sec(row_a["s2_ms"]),
            s3=fmt_sec(row_a["s3_ms"]),
            top_speed=top_spd_a,
            color=color_a,
            is_a=True,
        ),
        unsafe_allow_html=True,
    )

with card_col_2:
    st.markdown(
        driver_card(
            code=f"{row_b['code']} · {row_b['full_name']}",
            lap_time=fmt_lap(row_b["lap_time_ms"]),
            s1=fmt_sec(row_b["s1_ms"]),
            s2=fmt_sec(row_b["s2_ms"]),
            s3=fmt_sec(row_b["s3_ms"]),
            top_speed=top_spd_b,
            color=color_b,
            is_a=False,
        ),
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Main Analysis Tabs
# ---------------------------------------------------------------------------
tab_trace, tab_pedals, tab_mini, tab_corners = st.tabs([
    "📈 Speed & Delta",
    "🕹️ Pedals & Gear",
    "🏁 Mini-Sectors",
    "🎯 Corner Analysis",
])

# ---------------------------------------------------------------------------
# Tab 1: Speed & Delta
# ---------------------------------------------------------------------------
with tab_trace:
    st.markdown(
        f"**Speed comparison across distance** {estimated_badge()}",
        unsafe_allow_html=True,
    )

    fig_speed = go.Figure()

    # Driver A Speed
    fig_speed.add_trace(
        go.Scatter(
            x=tel_a["dist_m"],
            y=tel_a["speed"],
            name=f"{row_a['code']} Speed",
            line={"color": color_a, "width": 2.5},
            hovertemplate="<b>%{y:.1f} km/h</b> at %{x:.0f}m<extra>" + row_a["code"] + "</extra>",
        )
    )

    # Driver B Speed
    fig_speed.add_trace(
        go.Scatter(
            x=tel_b["dist_m"],
            y=tel_b["speed"],
            name=f"{row_b['code']} Speed",
            line={"color": color_b, "width": 2.5, "dash": "dot" if driver_a_code == driver_b_code else "solid"},
            hovertemplate="<b>%{y:.1f} km/h</b> at %{x:.0f}m<extra>" + row_b["code"] + "</extra>",
        )
    )

    # Overlay Corner Markers
    if not corners_df.empty:
        for _, c in corners_df.iterrows():
            fig_speed.add_vline(
                x=float(c["dist_m"]),
                line_width=1,
                line_dash="dash",
                line_color=COLORS["panel_border"],
                annotation_text=f"T{int(c['corner_no'])}",
                annotation_position="top left",
                annotation_font={"size": 9, "color": COLORS["muted"]},
            )

    fig_speed.update_layout(
        xaxis_title="Distance along lap (metres)",
        yaxis_title="Speed (km/h)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        height=380,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
    )
    apply_theme(fig_speed)
    st.plotly_chart(fig_speed, use_container_width=True)

    # Delta Time Trace
    st.markdown(
        f"**Lap Delta Time (approximate)** {estimated_badge()}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Relative delta time $\\Delta t(x) = t_{{{row_a['code']}}}(x) - t_{{{row_b['code']}}}(x)$. "
        f"Values below 0 indicate **{row_a['code']}** is ahead; values above 0 indicate **{row_b['code']}** is ahead."
    )

    delta_df = compute_delta_time(
        tel_a,
        tel_b,
        int(row_a["lap_time_ms"]),
        int(row_b["lap_time_ms"]),
    )

    if not delta_df.empty:
        fig_delta = go.Figure()
        fig_delta.add_trace(
            go.Scatter(
                x=delta_df["dist_m"],
                y=delta_df["delta_s"],
                mode="lines",
                name=f"Δ ({row_a['code']} - {row_b['code']})",
                line={"color": COLORS["accent"], "width": 2},
                fill="tozeroy",
                fillcolor="rgba(0, 210, 190, 0.12)",
                hovertemplate="Δt: <b>%{y:+.3f}s</b> at %{x:.0f}m<extra></extra>",
            )
        )
        fig_delta.add_hline(y=0, line_width=1, line_color=COLORS["muted"], line_dash="solid")

        fig_delta.update_layout(
            xaxis_title="Distance along lap (metres)",
            yaxis_title="Delta Time (s)",
            height=250,
            margin={"l": 40, "r": 20, "t": 10, "b": 40},
        )
        apply_theme(fig_delta)
        st.plotly_chart(fig_delta, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 2: Pedals & Inputs
# ---------------------------------------------------------------------------
with tab_pedals:
    st.markdown(f"**Driver Controls: Throttle, Brake & Gear** {estimated_badge()}", unsafe_allow_html=True)

    fig_pedals = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("Throttle (%)", "Brake Pedal", "Gear Selected"),
    )

    # Throttle
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_a["dist_m"],
            y=tel_a["throttle"],
            name=f"{row_a['code']} Throttle",
            line={"color": color_a, "width": 2},
        ),
        row=1,
        col=1,
    )
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_b["dist_m"],
            y=tel_b["throttle"],
            name=f"{row_b['code']} Throttle",
            line={"color": color_b, "width": 2, "dash": "dot"},
        ),
        row=1,
        col=1,
    )

    # Brake (0 / 1)
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_a["dist_m"],
            y=tel_a["brake"].astype(int),
            name=f"{row_a['code']} Brake",
            line={"color": color_a, "width": 1.5},
        ),
        row=2,
        col=1,
    )
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_b["dist_m"],
            y=tel_b["brake"].astype(int),
            name=f"{row_b['code']} Brake",
            line={"color": color_b, "width": 1.5, "dash": "dot"},
        ),
        row=2,
        col=1,
    )

    # Gear
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_a["dist_m"],
            y=tel_a["gear"],
            name=f"{row_a['code']} Gear",
            line={"color": color_a, "width": 1.5, "shape": "hv"},
        ),
        row=3,
        col=1,
    )
    fig_pedals.add_trace(
        go.Scatter(
            x=tel_b["dist_m"],
            y=tel_b["gear"],
            name=f"{row_b['code']} Gear",
            line={"color": color_b, "width": 1.5, "shape": "hv", "dash": "dot"},
        ),
        row=3,
        col=1,
    )

    fig_pedals.update_layout(
        height=550,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    fig_pedals.update_yaxes(range=[0, 105], row=1, col=1)
    fig_pedals.update_yaxes(tickvals=[0, 1], ticktext=["OFF", "ON"], range=[-0.1, 1.1], row=2, col=1)
    fig_pedals.update_yaxes(tickvals=list(range(1, 9)), range=[0.5, 8.5], row=3, col=1)
    fig_pedals.update_xaxes(title_text="Distance along lap (metres)", row=3, col=1)

    apply_theme(fig_pedals)
    st.plotly_chart(fig_pedals, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 3: Mini-Sectors
# ---------------------------------------------------------------------------
with tab_mini:
    st.markdown(
        f"**25 Equal-Distance Mini-Sectors** {estimated_badge()}",
        unsafe_allow_html=True,
    )
    st.caption("Each segment represents 4% of lap distance. Winner is determined by lowest segment time.")

    mini_df = calculate_mini_sectors(
        telems={driver_a_id: tel_a, driver_b_id: tel_b},
        driver_codes={driver_a_id: row_a["code"], driver_b_id: row_b["code"]},
        lap_times_ms={driver_a_id: int(row_a["lap_time_ms"]), driver_b_id: int(row_b["lap_time_ms"])},
        n_segments=25,
    )

    if not mini_df.empty:
        # Segment bar chart
        bar_colors = [color_a if code == row_a["code"] else color_b for code in mini_df["winner_code"]]
        fig_mini = go.Figure(
            go.Bar(
                x=[f"MS{i}" for i in mini_df["segment_idx"]],
                y=mini_df["margin_s"],
                marker_color=bar_colors,
                hovertemplate="Sector %{x}<br>Winner: <b>%{text}</b><br>Margin: +%{y:.3f}s<extra></extra>",
                text=mini_df["winner_code"],
            )
        )
        fig_mini.update_layout(
            xaxis_title="Mini-Sector",
            yaxis_title="Winning Margin (seconds)",
            height=300,
            margin={"l": 40, "r": 20, "t": 20, "b": 40},
        )
        apply_theme(fig_mini)
        st.plotly_chart(fig_mini, use_container_width=True)

        # Track Map Mini-Sectors Scatter
        st.markdown("**Track Map Segment Dominance**")
        fig_map = go.Figure()

        # Group points into 25 segments along track
        tot_d = tel_a["dist_m"].max()
        seg_len = tot_d / 25.0
        for i in range(25):
            seg_start = i * seg_len
            seg_end = (i + 1) * seg_len
            mask = (tel_a["dist_m"] >= seg_start) & (tel_a["dist_m"] <= seg_end)
            winner = mini_df.loc[mini_df["segment_idx"] == (i + 1), "winner_code"].values[0]
            seg_color = color_a if winner == row_a["code"] else color_b

            fig_map.add_trace(
                go.Scatter(
                    x=tel_a.loc[mask, "x"],
                    y=tel_a.loc[mask, "y"],
                    mode="lines",
                    line={"color": seg_color, "width": 4.5},
                    hoverinfo="none",
                    showlegend=False,
                )
            )

        # Add corner labels on track map
        if not corners_df.empty:
            fig_map.add_trace(
                go.Scatter(
                    x=corners_df["x"],
                    y=corners_df["y"],
                    mode="markers+text",
                    marker={"size": 7, "color": COLORS["session_best"]},
                    text=[f"T{int(n)}" for n in corners_df["corner_no"]],
                    textposition="top center",
                    textfont={"size": 10, "color": COLORS["text"]},
                    name="Corners",
                )
            )

        fig_map.update_layout(
            height=460,
            xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            yaxis={"showgrid": False, "zeroline": False, "showticklabels": False, "scaleanchor": "x", "scaleratio": 1},
            margin={"l": 20, "r": 20, "t": 20, "b": 20},
        )
        apply_theme(fig_map)
        st.plotly_chart(fig_map, use_container_width=True)

# ---------------------------------------------------------------------------
# Tab 4: Corner Analysis
# ---------------------------------------------------------------------------
with tab_corners:
    st.markdown(
        f"**Corner-by-Corner Detailed Metrics** {estimated_badge()}",
        unsafe_allow_html=True,
    )
    st.caption(
        "Braking window: 150m before corner entry to apex. Throttle window: apex to 100m after exit. "
        "Brake channel is on/off boolean (never braking force or pressure)."
    )

    cs_df = get_corner_stats(session_id, [driver_a_id, driver_b_id])

    if not cs_df.empty:
        # Pivot table per corner
        p_min_spd = cs_df.pivot(index="corner_no", columns="code", values="min_speed")
        p_brake = cs_df.pivot(index="corner_no", columns="code", values="brake_point_m")
        p_pickup = cs_df.pivot(index="corner_no", columns="code", values="throttle_pickup_m")
        p_exit = cs_df.pivot(index="corner_no", columns="code", values="exit_speed")

        corner_comp = pd.DataFrame(index=p_min_spd.index)
        corner_comp["Apex Min Spd " + row_a["code"]] = p_min_spd.get(row_a["code"])
        corner_comp["Apex Min Spd " + row_b["code"]] = p_min_spd.get(row_b["code"])
        corner_comp["Brake Point " + row_a["code"]] = p_brake.get(row_a["code"])
        corner_comp["Brake Point " + row_b["code"]] = p_brake.get(row_b["code"])
        corner_comp["Exit Spd " + row_a["code"]] = p_exit.get(row_a["code"])
        corner_comp["Exit Spd " + row_b["code"]] = p_exit.get(row_b["code"])

        # Display table
        st.dataframe(
            corner_comp.style.format("{:.1f}", na_rep="—"),
            use_container_width=True,
            height=400,
        )

# ---------------------------------------------------------------------------
# Methodology Notes Accordion
# ---------------------------------------------------------------------------
with st.expander("Methodology & Estimation Notes"):
    st.markdown(
        """
        - **10 m Fixed Grid**: Raw telemetry samples (whether from FastF1 car/pos data or physics interpolation)
          are resampled onto regular 10-metre intervals to enable point-by-point driver comparison.
        - **Delta Time Integration**: Time is integrated via $dt = dx / v(x)$ and scaled so the cumulative
          total exactly matches the driver's official transponder lap time, eliminating numerical integration drift.
        - **Brake Channel**: The FIA telemetry stream encodes brake as a binary state (pressed vs. released).
          Braking force and hydraulic pressures are proprietary team telemetry and not present in public timing.
        - **Mini-Sectors**: 25 equidistant segments (each 4% of track distance) calculate which driver
          was faster through each section of the lap.
        """
    )

footer()
