# Du-Du-Du · Formula 1 Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20%2F%20Supabase-336791.svg)](https://supabase.com/)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit%201.45-FF4B4B.svg)](https://streamlit.io/)
[![FastF1](https://img.shields.io/badge/Data-FastF1%203.8-red.svg)](https://docs.fastf1.dev/)
[![Tests](https://img.shields.io/badge/Tests-73%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Disclaimer**: *Unofficial fan-made analytics project. Not affiliated with, endorsed by, or associated with Formula 1, the FIA, Formula One Management (FOM), or any F1 team or driver. All F1 data is sourced from public endpoints via FastF1 (F1 Live Timing cache) and the Jolpica-F1 open API.*

---

## Overview

**Du-Du-Du** is an end-to-end Formula 1 data engineering and analytical platform analyzing Grand Prix pace, tyre degradation, pit stop execution, and driver telemetry.

Designed with rigorous engineering standards:
- **Idempotent ETL Pipeline**: Incremental upserts and partitioned session loading that can be safely re-run without duplicating or corrupting data.
- **Strict Data Cleaning Engine**: Algorithmic filtration distinguishing clean, representative racing laps from in-laps, out-laps, Safety Car windows, and wet weather running.
- **Data Quality Audit Trail**: Every session ingestion runs automated validation checks and records findings directly into a persistent `dq_log` audit table.
- **Materialized Aggregations**: Complex analytical queries (window functions, IQR distributions, and regression models) pre-aggregated in PostgreSQL for sub-second dashboard rendering.
- **Physics-Interpolated Telemetry**: Resamples car speeds, throttle, brake, gear, and spatial coordinates onto a standardized **10-metre distance grid**, enabling direct driver-versus-driver delta integration and corner telemetry profiling.

---

## Architecture

```text
  ┌─────────────────────────────────────────────────────────┐
  │                      Data Sources                       │
  │     FastF1 Live Timing API   ·   Jolpica Ergast API     │
  └────────────────────────────┬────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────┐
  │                 Python ETL Pipeline (etl/)               │
  │  • clean.py      Lap cleaning invariants (is_clean)     │
  │  • quality.py    Data quality checks & audit logging    │
  │  • telemetry.py  10m grid resampling & corner stats     │
  │  • season.py     Full-season calendar orchestrator      │
  └────────────────────────────┬────────────────────────────┘
                               │  Idempotent Upserts
                               ▼
  ┌─────────────────────────────────────────────────────────┐
  │               PostgreSQL Database Layer                 │
  │  • Core Schema: events, sessions, drivers, laps, ...    │
  │  • Telemetry:   telemetry_lap, corners, corner_stats    │
  │  • Materialized Views: mv_clean_lap_pace, mv_pit_loss   │
  │  • Audit Trail: dq_log                                  │
  └────────────────────────────┬────────────────────────────┘
                               │  Cached Reads (app/queries.py)
                               ▼
  ┌─────────────────────────────────────────────────────────┐
  │             Streamlit Analytics App (app/)              │
  │  • Home.py            Season KPIs & calendar status     │
  │  • 1_Race_Analysis.py Grid vs finish, stints & SC       │
  │  • 2_Pace_Analysis.py Clean pace IQR & tyre degradation │
  │  • 3_Pit_Stops.py     Pit loss delta & undercut timing  │
  │  • 4_Telemetry.py     Speed, delta & 25 mini-sectors    │
  └─────────────────────────────────────────────────────────┘
```

---

## Dashboard Capabilities

### 1. 🏁 Race Analysis (`1_Race_Analysis.py`)
- Official classification with championship points and driver finishing status.
- **Grid vs. Finish Position**: Interactive visualization highlighting net places gained/lost.
- **Stint Strategies**: Tyre compound swimlanes plotted lap-by-lap with overlaid Safety Car (SC), Virtual Safety Car (VSC), and Red Flag windows.
- **Reliability Breakdown**: Cumulative retirement summary categorized by mechanical fault vs. collision damage.

### 2. 📊 Pace Analysis (`2_Pace_Analysis.py`)
- **Clean-Lap Pace Distribution**: Interquartile range (IQR) boxplots and median lap times per driver for representative clean laps.
- **Tyre Degradation Modeling**: Compound-specific pace decay curves (OLS regression slope in ms/lap) bucketed by tyre age.
- **Teammate Gaps**: Qualifying single-lap deltas and race median pace differentials between drivers in equal machinery.

### 3. 🔧 Pit Stops & Strategy (`3_Pit_Stops.py`)
- **Pit Lane Delta & Pit Loss**: Time lost during pit in-lap and out-lap relative to clean-lap baseline, isolating stationary stops and cold-tyre warm-up penalties.
- **Undercut Analysis**: Tracks tactical early stops within 3-second gaps to evaluate position changes once both drivers cycle through the pits.
- Transparently tagged with **`ESTIMATED`** badges to acknowledge fuel burn and traffic variances.

### 4. ⚡ Driver Telemetry (`4_Telemetry.py`)
- **Fastest Lap Overlay**: Resampled onto a uniform **10-metre grid** for head-to-head driver analysis.
- **Speed & Delta Trace**: Real-time speed comparison with circuit corner markers (T1–T14) and cumulative time delta $\Delta t(x)$ scaled to official transponder lap times.
- **Pedals & Inputs**: Multi-axis telemetry for throttle application (0–100%), brake pedal binary state, and gear selection.
- **25 Mini-Sectors**: Track divided into 25 equal distance segments showing sectional driver dominance and winning margins.
- **Corner-by-Corner Metrics**: Braking point distance, minimum apex speed, throttle pickup point, and corner exit speed.

---

## Data Cleaning Standards

To guarantee analytical validity, raw timing data is processed through rigorous cleaning invariants before metric computation:

1. **Not Lap 1**: Standing starts distort pace due to standing acceleration and traffic congestion.
2. **Not In-Lap / Out-Lap**: Pit lane entry/exit transitions skew lap durations.
3. **Not Neutralized**: Any lap under Yellow Flag, Safety Car, Virtual Safety Car, or Red Flag (track status $\ge 2$) is disqualified.
4. **Dry Compounds Only**: Wet and Intermediate running is segregated from slick tyre degradation models.
5. **FastF1 Accuracy Flag**: FastF1 transponder validation check (`IsAccurate = True`).
6. **No Implausible Outliers**: Outliers beyond $\pm 10\%$ of driver median or under track physical minimums are quarantined into `dq_log`.

Detailed methodology is documented in [`docs/methodology.md`](docs/methodology.md) and [`docs/data_dictionary.md`](docs/data_dictionary.md).

---

## Getting Started

### 1. Prerequisites
- Python 3.11+
- PostgreSQL database instance (Neon, Supabase, or local PostgreSQL)

### 2. Installation

```bash
git clone https://github.com/MetaFazer/du-du-dudu.git
cd du-du-dudu

# Create and activate virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

Create your `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Set your database connection URL in `.env`:
```env
DATABASE_URL=postgresql+psycopg://username:password@host:5432/dbname?sslmode=require
FF1_CACHE_DIR=fastf1_cache
```

### 4. Apply Schema & Load Data

```bash
# 1. Apply PostgreSQL schema tables and indexes
python -m etl.run --schema-only

# 2. Ingest Round 1 (Australian Grand Prix) with laps, results, and pit stops
python -m etl.run --season 2025 --round 1

# 3. Load 10m grid telemetry and corner statistics
python -m etl.run --season 2025 --round 1 --telemetry

# 4. Refresh materialized views
python -m etl.run --views
```

To ingest all completed rounds across the entire season in the background:
```bash
python -m etl.run --season 2025 --full-season
```

### 5. Launch the Analytics App

```bash
# Windows:
$env:PYTHONPATH = "."; .venv\Scripts\streamlit run app/Home.py

# macOS/Linux:
PYTHONPATH="." streamlit run app/Home.py
```

Open your browser at `http://localhost:8501`.

---

## Running Tests

All unit tests run independently without external network or database dependencies:

```bash
pytest tests/ -v
```

The test suite covers:
- Lap cleaning rule invariants (`tests/test_clean.py`)
- Data quality validation checks and audit logging (`tests/test_quality.py`)
- Season calendar and sprint weekend detection (`tests/test_season.py`)
- Telemetry 10m resampling, delta time integration, and corner stats (`tests/test_telemetry.py`)

---

## Repository Structure

```text
du-du-du/
├── app/
│   ├── Home.py                  # Main landing dashboard
│   ├── theme.py                 # F1 design tokens, dark CSS & Plotly template
│   ├── queries.py               # Cached, read-only SQL query interface
│   └── pages/
│       ├── 1_Race_Analysis.py   # Results, grid vs finish, tyre stints
│       ├── 2_Pace_Analysis.py   # Clean pace boxplots, tyre deg, teammate gaps
│       ├── 3_Pit_Stops.py       # Pit loss delta, undercut tracking
│       └── 4_Telemetry.py       # 10m grid speed, delta time, mini-sectors
├── etl/
│   ├── db.py                    # Engine connection singleton & schema migrations
│   ├── clean.py                 # Pure cleaning rules & outlier filters
│   ├── quality.py               # Automated DQ checks & audit log persistence
│   ├── ingest.py                # FastF1 + Jolpica race weekend ingestion
│   ├── telemetry.py             # 10m grid resampling, delta math & corner stats
│   ├── season.py                # Full season loader & sprint detection
│   ├── views.py                 # Materialized view refresh helper
│   └── run.py                   # Central CLI ETL runner
├── sql/
│   ├── schema.sql               # PostgreSQL tables, constraints, and indexes
│   ├── views.sql                # Materialized views for heavy aggregates
│   └── analysis/                # 7 reference SQL queries for findings
├── docs/
│   ├── methodology.md           # Engineering decisions & cleaning logic
│   ├── data_dictionary.md       # Column definitions for all 12 tables
│   └── findings.md              # Empirical findings report & insights
└── tests/                       # Complete unit test suite (73 passing tests)
```

---

## Key Findings

A summary of empirical findings from the 2025 season is maintained in [`docs/findings.md`](docs/findings.md). Topics include:
- Median clean-lap pace hierarchies and stint consistency.
- Medium vs. Hard compound degradation slopes and thermal wear.
- Pit loss penalties (~30.8s avg) and cold-tyre out-lap warm-up deltas.
- Intra-team qualifying margins and driver adaptation curves.
- Reliability distributions and early-season mechanical failure modes.
