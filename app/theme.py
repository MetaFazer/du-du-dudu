"""
app/theme.py – Centralized colors, CSS, Plotly template, and HTML components.

All pages import from here. Nothing hardcoded in individual page files.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Color palette  (spec §9)
# ---------------------------------------------------------------------------

COLORS = {
    "bg":            "#0c0d11",
    "panel":         "#13141a",
    "panel_border":  "#23252e",
    "text":          "#e8e8ec",
    "muted":         "#6b6d78",
    "accent":        "#e10600",
    "session_best":  "#b36bff",
    "warning":       "#f5c242",
    "highlight_bg":  "#1a1114",
    "driver_a":      "#3671c6",
    "driver_b":      "#ff8000",
    "tyre_soft":     "#ff3b3b",
    "tyre_medium":   "#f5c242",
    "tyre_hard":     "#e8e8ec",
    "tyre_inter":    "#43b047",
    "tyre_wet":      "#0067ff",
    "gridline":      "#1d1f27",
}

TYRE_COLORS: dict[str, str] = {
    "SOFT":         COLORS["tyre_soft"],
    "MEDIUM":       COLORS["tyre_medium"],
    "HARD":         COLORS["tyre_hard"],
    "INTERMEDIATE": COLORS["tyre_inter"],
    "WET":          COLORS["tyre_wet"],
    "UNKNOWN":      COLORS["muted"],
}

_GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=JetBrains+Mono:wght@400;600;700&"
    "family=IBM+Plex+Sans:wght@400;500;600&"
    "display=swap"
)

# ---------------------------------------------------------------------------
# CSS  (injected once per page via inject_css())
# ---------------------------------------------------------------------------

_CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{_GOOGLE_FONTS}" rel="stylesheet">

<style>
/* ── Base ───────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
    background-color: {COLORS['bg']} !important;
    color: {COLORS['text']};
    font-family: 'IBM Plex Sans', sans-serif;
}}

[data-testid="stSidebar"] {{
    background: {COLORS['panel']} !important;
    border-right: 1px solid {COLORS['panel_border']};
}}

/* ── Header strip ───────────────────────────────────────────── */
.du-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 0 18px 0;
    border-bottom: 1px solid {COLORS['panel_border']};
    margin-bottom: 20px;
}}
.du-logo {{
    width: 36px; height: 36px;
    background: {COLORS['accent']};
    border-radius: 4px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700; font-size: 14px;
    color: #fff;
    flex-shrink: 0;
}}
.du-title {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 20px;
    letter-spacing: 0.05em;
    color: {COLORS['text']};
    line-height: 1;
}}
.du-subtitle {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: {COLORS['muted']};
    font-family: 'JetBrains Mono', monospace;
    margin-top: 2px;
}}
.du-chip {{
    margin-left: auto;
    background: {COLORS['panel']};
    border: 1px solid {COLORS['panel_border']};
    border-radius: 4px;
    padding: 4px 10px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: {COLORS['muted']};
}}

/* ── Panels ─────────────────────────────────────────────────── */
.du-panel {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['panel_border']};
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 12px;
}}

/* ── Stat tiles ─────────────────────────────────────────────── */
[data-testid="metric-container"] {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['panel_border']};
    border-radius: 6px;
    padding: 14px 16px;
}}
[data-testid="metric-container"] [data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.55rem;
    font-weight: 700;
    color: {COLORS['text']};
}}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: {COLORS['muted']};
    font-family: 'JetBrains Mono', monospace;
}}

/* ── Selectbox / inputs ─────────────────────────────────────── */
[data-testid="stSelectbox"] label,
[data-testid="stMultiSelect"] label {{
    font-size: 10px !important;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: {COLORS['muted']} !important;
    font-family: 'JetBrains Mono', monospace !important;
}}

/* ── Custom table ───────────────────────────────────────────── */
.du-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
}}
.du-table th {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: {COLORS['muted']};
    padding: 6px 10px;
    border-bottom: 1px solid {COLORS['panel_border']};
    text-align: left;
}}
.du-table td {{
    padding: 7px 10px;
    border-bottom: 1px solid {COLORS['panel_border']};
    color: {COLORS['text']};
}}
.du-table tr:last-child td {{ border-bottom: none; }}
.du-table tr:hover td {{ background: {COLORS['highlight_bg']}; }}
.du-table .best {{ color: {COLORS['session_best']}; font-weight: 600; }}
.du-table .a-gains {{ color: {COLORS['driver_a']}; }}
.du-table .b-gains {{ color: {COLORS['driver_b']}; }}
.du-table .red {{ color: {COLORS['accent']}; }}

/* Selected/highlighted row: red left edge */
.du-table tr.selected td:first-child {{
    border-left: 3px solid {COLORS['accent']};
    background: {COLORS['highlight_bg']};
}}

/* ── Driver cards ───────────────────────────────────────────── */
.du-driver-card {{
    border-radius: 6px;
    padding: 16px;
    border-width: 1px;
    border-style: solid;
}}
.du-card-code {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 0.05em;
}}
.du-card-time {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    color: {COLORS['muted']};
    float: right;
    margin-top: 4px;
}}
.du-card-sectors {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-top: 12px;
}}
.du-card-sector-label {{
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: {COLORS['muted']};
    font-family: 'JetBrains Mono', monospace;
}}
.du-card-sector-val {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 600;
}}

/* ── SC/VSC bands (plotly shapes label) ─────────────────────── */
.sc-band-label {{
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: {COLORS['warning']};
}}

/* ── Footer ─────────────────────────────────────────────────── */
.du-footer {{
    margin-top: 48px;
    padding: 12px 0;
    border-top: 1px solid {COLORS['panel_border']};
    font-size: 11px;
    color: {COLORS['muted']};
    text-align: center;
    font-family: 'IBM Plex Sans', sans-serif;
}}

/* ── Plotly container ───────────────────────────────────────── */
[data-testid="stPlotlyChart"] > div {{
    border-radius: 6px;
    overflow: hidden;
}}

/* ── Estimated badge ────────────────────────────────────────── */
.est-badge {{
    display: inline-block;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: {COLORS['warning']};
    border: 1px solid {COLORS['warning']};
    border-radius: 3px;
    padding: 1px 5px;
    font-family: 'JetBrains Mono', monospace;
    vertical-align: middle;
    margin-left: 6px;
}}
</style>
"""

FOOTER_HTML = (
    '<div class="du-footer">'
    "Unofficial fan project. Not affiliated with Formula 1, the FIA or any team."
    "</div>"
)


# ---------------------------------------------------------------------------
# Plotly shared template
# ---------------------------------------------------------------------------

def _make_plotly_template() -> dict:
    """Return a Plotly layout dict to apply to every figure."""
    return {
        "layout": {
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor":  COLORS["panel"],
            "font": {
                "family": "JetBrains Mono, monospace",
                "color":  COLORS["text"],
                "size":   12,
            },
            "xaxis": {
                "gridcolor":     COLORS["gridline"],
                "linecolor":     COLORS["panel_border"],
                "tickfont":      {"family": "JetBrains Mono", "size": 11},
                "title_font":    {"family": "JetBrains Mono", "size": 11},
                "zerolinecolor": COLORS["gridline"],
            },
            "yaxis": {
                "gridcolor":     COLORS["gridline"],
                "linecolor":     COLORS["panel_border"],
                "tickfont":      {"family": "JetBrains Mono", "size": 11},
                "title_font":    {"family": "JetBrains Mono", "size": 11},
                "zerolinecolor": COLORS["gridline"],
            },
            "legend": {
                "bgcolor":     "rgba(0,0,0,0)",
                "font":        {"family": "JetBrains Mono", "size": 11},
                "borderwidth": 0,
            },
            "modebar": {"remove": ["zoom2d", "pan2d", "select2d", "lasso2d",
                                   "zoomIn2d", "zoomOut2d", "autoScale2d",
                                   "resetScale2d", "toggleSpikelines"]},
            "margin": {"t": 40, "b": 40, "l": 50, "r": 20},
            "hoverlabel": {
                "bgcolor":    COLORS["panel"],
                "bordercolor": COLORS["panel_border"],
                "font":       {"family": "JetBrains Mono", "size": 12},
            },
        }
    }


PLOTLY_TEMPLATE = _make_plotly_template()


def apply_theme(fig, title: str = "") -> object:
    """Apply the shared Plotly theme to a figure and set optional title."""
    t = PLOTLY_TEMPLATE["layout"]
    fig.update_layout(
        **dict(t.items()),
        title={
            "text": title,
            "font": {"family": "JetBrains Mono", "size": 13, "color": COLORS["text"]},
            "x": 0.01,
            "xanchor": "left",
        } if title else {},
    )
    return fig


# ---------------------------------------------------------------------------
# Page-level helpers
# ---------------------------------------------------------------------------

def inject_css() -> None:
    """Inject base CSS and Google Fonts. Call at the top of every page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "F1 ANALYTICS", chip: str = "2025") -> None:
    """Render the standardised DU-DU-DU page header."""
    st.markdown(
        f"""
        <div class="du-header">
            <div class="du-logo">DU</div>
            <div>
                <div class="du-title">DU-DU-DU</div>
                <div class="du-subtitle">{subtitle}</div>
            </div>
            <div class="du-chip">{chip}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer() -> None:
    """Render the standard disclaimer footer."""
    st.markdown(FOOTER_HTML, unsafe_allow_html=True)


def estimated_badge() -> str:
    """Return HTML for the 'ESTIMATED' badge inline in markdown."""
    return '<span class="est-badge">ESTIMATED</span>'


def driver_card(
    code: str,
    lap_time: str,
    s1: str,
    s2: str,
    s3: str,
    top_speed: str,
    color: str,
    *,
    is_a: bool = True,
) -> str:
    """Return HTML for a driver telemetry card."""
    bg = f"color-mix(in srgb, {color} 12%, {COLORS['panel']})"
    return f"""
    <div class="du-driver-card" style="background:{bg}; border-color:{color};">
        <span class="du-card-code" style="color:{color};">{code}</span>
        <span class="du-card-time">{lap_time}</span>
        <div style="clear:both; margin-top:10px;">
            <div class="du-card-sectors">
                <div>
                    <div class="du-card-sector-label">S1</div>
                    <div class="du-card-sector-val">{s1}</div>
                </div>
                <div>
                    <div class="du-card-sector-label">S2</div>
                    <div class="du-card-sector-val">{s2}</div>
                </div>
                <div>
                    <div class="du-card-sector-label">S3</div>
                    <div class="du-card-sector-val">{s3}</div>
                </div>
            </div>
            <div style="margin-top:8px;">
                <span class="du-card-sector-label">TOP SPEED&nbsp;</span>
                <span class="du-card-sector-val">{top_speed}</span>
            </div>
        </div>
    </div>
    """


def tyre_dot(compound: str) -> str:
    """Return a colored HTML dot for a tyre compound."""
    color = TYRE_COLORS.get(compound.upper(), COLORS["muted"])
    label = compound[0] if compound else "?"
    return (
        f'<span style="display:inline-block;width:14px;height:14px;'
        f'border-radius:50%;background:{color};color:#000;'
        f'font-size:9px;font-weight:700;line-height:14px;'
        f'text-align:center;font-family:JetBrains Mono,monospace;">{label}</span>'
    )


def ms_to_str(ms: float | None) -> str:
    """Format milliseconds as M:SS.mmm for display."""
    if ms is None:
        return "—"
    ms = int(ms)
    mins = ms // 60_000
    secs = (ms % 60_000) / 1000
    return f"{mins}:{secs:06.3f}"


def delta_str(ms: float | None, *, invert: bool = False) -> str:
    """Format a millisecond delta as +/-S.mmm."""
    if ms is None:
        return "—"
    val = -ms if invert else ms
    sign = "+" if val >= 0 else ""
    return f"{sign}{val/1000:.3f}s"
