"""
app/Home.py – Du-Du-Dudu landing dashboard.

Shows:
  • Season overview KPIs (rounds loaded, laps in DB)
  • Calendar table with loaded/pending status
  • DB health + DQ log summary
  • Quick-nav cards to each analysis page
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Du-Du-Dudu · F1 Analytics",
    page_icon="🏎",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app.queries import get_events  # noqa: E402
from app.theme import COLORS, footer, inject_css, page_header  # noqa: E402

inject_css()
page_header("Du-Du-Dudu", "F1 ANALYTICS · 2025")

# ---------------------------------------------------------------------------
# Quick-nav cards
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:0 0 28px 0;">
        <a href="/Race_Analysis" target="_self" style="text-decoration:none;">
            <div style="background:{panel};border:1px solid {border};border-radius:8px;padding:20px;
                        transition:border-color 0.2s;">
                <div style="font-size:28px;">🏁</div>
                <div style="font-size:14px;font-weight:600;color:{text};margin-top:8px;">Race Analysis</div>
                <div style="font-size:12px;color:{muted};margin-top:4px;">Results · grid vs finish · stints · reliability</div>
            </div>
        </a>
        <a href="/Pace_Analysis" target="_self" style="text-decoration:none;">
            <div style="background:{panel};border:1px solid {border};border-radius:8px;padding:20px;">
                <div style="font-size:28px;">📊</div>
                <div style="font-size:14px;font-weight:600;color:{text};margin-top:8px;">Pace Analysis</div>
                <div style="font-size:12px;color:{muted};margin-top:4px;">Clean lap pace · tyre deg · teammate gap</div>
            </div>
        </a>
        <a href="/Pit_Stops" target="_self" style="text-decoration:none;">
            <div style="background:{panel};border:1px solid {border};border-radius:8px;padding:20px;">
                <div style="font-size:28px;">🔧</div>
                <div style="font-size:14px;font-weight:600;color:{text};margin-top:8px;">Pit Stops</div>
                <div style="font-size:12px;color:{muted};margin-top:4px;">Strategy · delta · undercut (estimated)</div>
            </div>
        </a>
        <a href="/Telemetry" target="_self" style="text-decoration:none;">
            <div style="background:{panel};border:1px solid {border};border-radius:8px;padding:20px;">
                <div style="font-size:28px;">⚡</div>
                <div style="font-size:14px;font-weight:600;color:{text};margin-top:8px;">Telemetry</div>
                <div style="font-size:12px;color:{muted};margin-top:4px;">Speed · delta · 10m grid · corners</div>
            </div>
        </a>
    </div>
    """.format(
        panel=COLORS["panel"],
        border=COLORS["panel_border"],
        text=COLORS["text"],
        muted=COLORS["muted"],
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# DB health & KPIs
# ---------------------------------------------------------------------------
try:
    from sqlalchemy import text

    from app.queries import _get_engine

    engine = _get_engine()
    with engine.connect() as conn:
        n_events   = conn.execute(text("SELECT COUNT(*) FROM events WHERE season = 2025")).scalar() or 0
        n_sessions = conn.execute(text("SELECT COUNT(*) FROM sessions")).scalar() or 0
        n_laps     = conn.execute(text("SELECT COUNT(*) FROM laps")).scalar() or 0
        n_results  = conn.execute(text("SELECT COUNT(*) FROM results")).scalar() or 0
        n_drivers  = conn.execute(text("SELECT COUNT(*) FROM drivers")).scalar() or 0
        loaded_rounds = conn.execute(text(
            "SELECT COUNT(DISTINCT e.round) FROM sessions s "
            "JOIN events e ON e.event_id = s.event_id WHERE e.season = 2025"
        )).scalar() or 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Rounds loaded", f"{loaded_rounds} / {n_events}")
    col2.metric("Sessions in DB", n_sessions)
    col3.metric("Laps in DB", f"{n_laps:,}")
    col4.metric("Results rows", f"{n_results:,}")
    col5.metric("Drivers", n_drivers)

    st.success("✅ Database connected to Supabase")
except Exception as exc:
    st.error(f"❌ Database error: {exc}")

st.markdown("---")

# ---------------------------------------------------------------------------
# Calendar: which rounds are loaded
# ---------------------------------------------------------------------------
st.markdown("#### 2025 Season Calendar")

events = get_events(2025)
if not events.empty:
    try:
        from sqlalchemy import text as sqlt

        from app.queries import _get_engine
        eng = _get_engine()
        with eng.connect() as c:
            loaded = c.execute(sqlt(
                "SELECT DISTINCT e.round FROM sessions s "
                "JOIN events e ON e.event_id = s.event_id WHERE e.season = 2025"
            )).fetchall()
        loaded_set = {r[0] for r in loaded}
    except Exception:
        loaded_set = set()

    events["Status"] = events["round"].apply(
        lambda r: "✅ Loaded" if r in loaded_set else "⏳ Pending"
    )
    display = events[["round", "name", "circuit", "country", "date", "Status"]].copy()
    display.columns = ["Round", "Event", "Circuit", "Country", "Date", "Status"]
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Round": st.column_config.NumberColumn("Rnd", width=50),
            "Status": st.column_config.TextColumn("Status", width=100),
        },
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# DQ log summary
# ---------------------------------------------------------------------------
st.markdown("#### Data Quality Log")
try:
    from sqlalchemy import text as sqlt2

    from app.queries import _get_engine
    eng2 = _get_engine()
    with eng2.connect() as c:
        dq = c.execute(sqlt2(
            "SELECT severity, COUNT(*) AS cnt FROM dq_log GROUP BY severity ORDER BY severity"
        )).fetchall()
        dq_recent = c.execute(sqlt2(
            "SELECT run_id, session_label, check_name, severity, message, created_at "
            "FROM dq_log ORDER BY created_at DESC LIMIT 20"
        )).fetchall()

    if dq:
        cols = st.columns(len(dq))
        for col, (severity, cnt) in zip(cols, dq, strict=False):
            col.metric(label=severity, value=int(cnt))
        if dq_recent:
            import pandas as pd
            dq_df = pd.DataFrame(
                dq_recent,
                columns=["run_id", "session", "check", "severity", "message", "at"]
            )
            dq_df["run_id"] = dq_df["run_id"].astype(str).str[:8]
            dq_df["at"] = pd.to_datetime(dq_df["at"]).dt.strftime("%m-%d %H:%M")
            st.dataframe(dq_df, hide_index=True, use_container_width=True)
    else:
        st.caption("No DQ log entries yet — run ETL first.")
except Exception as exc:
    st.caption(f"DQ log unavailable: {exc}")

st.markdown("---")
st.markdown(
    """
    **ETL quick-reference**
    ```bash
    # Apply schema (first time or after schema changes)
    python -m etl.run --schema-only

    # Load one round (e.g. Australian GP = round 1)
    python -m etl.run --season 2025 --round 1

    # Refresh materialized views after loading data
    python -m etl.run --views

    # Load all past rounds
    python -m etl.run --season 2025 --full-season
    ```
    """
)

footer()
