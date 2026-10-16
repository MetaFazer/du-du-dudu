# Du-Du-Dudu · Formula 1 Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20%2F%20Supabase-336791.svg)](https://supabase.com/)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit%201.45-FF4B4B.svg)](https://du-du-dudu.streamlit.app/)
[![FastF1](https://img.shields.io/badge/Data-FastF1%203.8-red.svg)](https://docs.fastf1.dev/)
[![Tests](https://img.shields.io/badge/Tests-73%20passed-brightgreen.svg)](tests/)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-du--du--dudu.streamlit.app-00C0F2?style=flat&logo=streamlit)](https://du-du-dudu.streamlit.app/)

> **Disclaimer**: *Unofficial fan-made analytics project. Not affiliated with, endorsed by, or associated with Formula 1, the FIA, Formula One Management (FOM), or any F1 team or driver. All F1 data is sourced from public endpoints via FastF1, Jolpica-F1, and OpenF1.*

---

## What is Du-Du-Dudu?

**Du-Du-Dudu** is an end-to-end Formula 1 data engineering and race analytics platform covering the complete 2025 FIA Formula One World Championship season. 

While TV broadcasts only show superficial graphics like a 2-second wheel-change or raw lap times, **Du-Du-Dudu** dives beneath the surface to explain **why** races are won or lost: measuring true clean-lap car pace, compound tyre degradation, undercut strategic executions, and corner-by-corner telemetry deltas.

| 🏁 24 / 24 Rounds | 🏎️ 34,407 Laps | ⚡ 528,247 Telemetry Points | 🔧 963 Pit Stops | ⚡ <50ms Query Latency |
| :---: | :---: | :---: | :---: | :---: |
| Full 2025 Season | 31,045 Clean Laps | 10m Spatial Grid | Fully Reconstructed | 7 Materialized Views |

---

## Formula 1 Concepts Made Simple

If you don't follow Formula 1 closely, here are the core concepts analyzed by the platform explained in plain English:

### 1. What is an Undercut Pit Stop?
In modern Formula 1, newer tyres produce significantly more grip than worn tyres—often making a car **1.0 to 2.5 seconds faster per lap**. When Car B is stuck behind Car A and cannot overtake due to aerodynamic turbulence ("dirty air"), Car B's strategist calls for an **undercut**:

```text
Lap 20:   [ Car A (Old Tyres) ] ──────────> Stays out on track (running 1:32.5s)
          [ Car B (Old Tyres) ] ──┐
                                  │ PITS for brand-new tyres
Lap 21:   [ Car B (NEW Tyres) ] ◄─┘ Re-enters in clean air, flying at 1:30.5s! (+2.0s advantage)
          [ Car A (Old Tyres) ] ──────────> Still on track, struggling for grip
                                  ┌─ Car A finally pits on Lap 22
Lap 22:   [ Car B (At Speed)  ] ──┼────────────────────────► CAR B TAKES THE LEAD!
          [ Car A (Exiting)   ] ──┘ Re-enters behind Car B
```

* **Du-Du-Dudu Implementation**: The system detects opposing driver pairs within 3.0 seconds on track that pit within 3 laps of each other, calculating gap deltas and undercut success rates across all 24 circuits (labeled `ESTIMATED`).

---

### 2. Pit Box Stationary Time vs. Total Pit Loss Delta
Fans celebrate a lightning-fast **2.2-second wheel change**, but that is only a fraction of the real strategic cost:
* **Stationary Box Duration**: The pure mechanical time the car is stopped having tyres bolted on.
* **Pit Loss Delta**: The **total racing time sacrificed** by entering the pit lane under the 80 km/h speed limiter compared to a car that stayed at full racing speed (320+ km/h) on the main straight:
  $$\text{Pit Loss Delta} = (\text{In-Lap Time} + \text{Out-Lap Time}) - (2 \times \text{Driver Median Clean Flying Lap})$$
  *Depending on circuit layout, this cost ranges from **~18.5s** (Austria) to over **~26.5s** (Silverstone & Singapore).*

---

### 3. What is Tyre Degradation?
Formula 1 cars use three dry slick tyre compounds supplied by Pirelli: **Soft (red)**, **Medium (yellow)**, and **Hard (white)**. 
* **Softs** offer the highest grip but wear down quickly.
* **Hards** are durable but inherently slower.
As tyres undergo thermal cycling and tread loss, lap times slow down progressively until hitting the "cliff". **Du-Du-Dudu** tracks exact tyre age across all stints to calculate linear degradation slopes (milliseconds lost per lap).

---

### 4. What is a "Clean Lap"?
Raw timing data is heavily contaminated by traffic, yellow flags, Safety Cars (SC), Virtual Safety Cars (VSC), and pit in/out laps. To evaluate genuine car performance, **Du-Du-Dudu** applies a strict deterministic 5-point cleaning rule:
1. **Exclude Lap 1**: Standing starts and lap-one congestion distort representative pace.
2. **Exclude In-Laps & Out-Laps**: Driving under pit lane speed limiters artificially inflates lap times.
3. **Strict Green Flag Status**: Only track status `1` (Green) is admitted. All SC, VSC, and yellow flag laps are eliminated.
4. **Timing Accuracy**: Official transponder `is_accurate` flag must be true.
5. **Dry Compounds Only**: Separates wet and intermediate running from dry slick pace baselines.

---

### 5. Why Resample Telemetry to a 10-Meter Spatial Grid?
F1 cars log telemetry against elapsed time. However, comparing two drivers across time is scientifically flawed: if Driver A is driving faster than Driver B, they are at completely different points on the circuit at any given second.

To compare drivers accurately, **Du-Du-Dudu resamples all telemetry onto a normalized spatial grid spaced at exact 10-metre intervals** (0m, 10m, 20m ... 5,280m). This enables direct, apples-to-apples overlays of speeds, throttle positions, and braking points at the exact same physical coordinates on the circuit.

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.11, 3.12, or 3.13
- PostgreSQL database instance (Supabase, Neon, or local PostgreSQL)

### 2. Clone and Setup Environment

```bash
# Clone the repository
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

### 3. Configure Database Credentials

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Set your PostgreSQL connection string in `.env`:
```env
DATABASE_URL=postgresql+psycopg://username:password@host:5432/dbname?sslmode=require
FF1_CACHE_DIR=fastf1_cache
```

### 4. Initialize Database & Run ETL

```bash
# 1. Create tables, constraints, and indexes
python -m etl.run --schema-only

# 2. Ingest Round 1 (Australian Grand Prix) with laps and pit stops
python -m etl.run --season 2025 --round 1

# 3. Resample 10m spatial telemetry and extract corner statistics
python -m etl.run --season 2025 --round 1 --telemetry

# 4. Refresh all 7 PostgreSQL materialized views
python -m etl.run --views
```

> **Full Season Ingestion**: To ingest all 24 rounds across the entire championship season:
> ```bash
> python -m etl.run --season 2025 --full-season
> ```

### 5. Launch the Streamlit App

```bash
# Windows:
$env:PYTHONPATH = "."; .venv\Scripts\streamlit run app/Home.py

# macOS/Linux:
PYTHONPATH="." streamlit run app/Home.py
```
Open your browser at `http://localhost:8501`.

---

## End-to-End System Architecture

```text
                      ┌─────────────────────────────────────────────────────────┐
                      │                      DATA INGESTION                     │
                      │  • FastF1 (High-res telemetry, speed, throttle, brake)  │
                      │  • Jolpica Ergast REST API (Failover results & laps)    │
                      │  • OpenF1 API (Enriches tyre compounds & stint ages)    │
                      └────────────────────────────┬────────────────────────────┘
                                                   │
                                                   ▼
                      ┌─────────────────────────────────────────────────────────┐
                      │                ETL & RESAMPLING PIPELINE                │
                      │  • clean.py:     Deterministic 5-point clean lap filter │
                      │  • quality.py:   Automated DQ audit checks              │
                      │  • telemetry.py: 10m grid spatial interpolation         │
                      │  • stints.py:    Tyre life & stint age mapping          │
                      └────────────────────────────┬────────────────────────────┘
                                                   │  Idempotent Upserts
                                                   ▼
                      ┌─────────────────────────────────────────────────────────┐
                      │              POSTGRESQL ANALYTICAL STORAGE              │
                      │  • Core Schema:  events, sessions, drivers, laps, ...   │
                      │  • Telemetry:    telemetry_10m, corner_stats            │
                      │  • Audit Trail:  data_quality_audit                     │
                      │  • 7 Materialized Views (Indexed for <50ms read latency)│
                      └────────────────────────────┬────────────────────────────┘
                                                   │  Connection Pooling
                                                   ▼
                      ┌─────────────────────────────────────────────────────────┐
                      │                STREAMLIT WEB DASHBOARD                  │
                      │  • 1_Race_Analysis.py:  Results, Grid vs Finish, Stints │
                      │  • 2_Pace_Analysis.py:  Clean Pace IQR, Tyre Deg Models │
                      │  • 3_Pit_Stops.py:      Pit Loss Delta & Undercut Pairs │
                      │  • 4_Telemetry.py:      10m Grid Speed & Mini-Sectors   │
                      └─────────────────────────────────────────────────────────┘
```

---

## The Tri-API Hybrid Ingestion Pipeline

Official Formula 1 timing CDNs frequently restrict uncached sessions with `HTTP 401 Unauthorized` responses. To guarantee 100% data availability across all 24 championship rounds, **Du-Du-Dudu** operates a hybrid 3-API ingestion engine:

```text
    ┌───────────────────────────┐
    │     FastF1 (Primary)      │──► Success ──► Ingests high-resolution telemetry,
    └─────────────┬─────────────┘                sector splits, and speed traps.
                  │
          (If CDN 401 Block)
                  │
                  ▼
    ┌───────────────────────────┐
    │  Jolpica Ergast (Fallback)│──► Free, open REST API providing all 24 race results,
    └─────────────┬─────────────┘    qualifying grids, and transponder lap times.
                  │
                  ▼
    ┌───────────────────────────┐
    │    OpenF1 (Enrichment)    │──► Jolpica laps lack tyre compounds (marked 'UNKNOWN').
    └───────────────────────────┘    OpenF1 enriches 25,584 laps with exact Soft, Medium,
                                     and Hard compounds and tyre age counters.
```

---

## Database Architecture: The 7 Materialized Views

To achieve sub-second dashboard performance, heavy window functions and percentiles are precomputed into **7 PostgreSQL Materialized Views** with unique indexes, cutting dashboard query latency from **~3.2 seconds down to <50 milliseconds**:

| Materialized View | Granularity | Precomputed Analytical Metric |
| :--- | :--- | :--- |
| `mv_clean_lap_pace` | Driver per session | Median clean lap, IQR (25th/75th percentiles), fastest clean lap, valid lap count. |
| `mv_pit_loss` | Driver pit stop | In-lap, out-lap, stationary duration, and net racing pit loss delta relative to flying baseline. |
| `mv_undercut` | Driver pair per stop | Pre-stop gap, post-stop gap, net delta, and undercut success/failure boolean flag. |
| `mv_tyre_deg` | Compound & tyre age | Pace delta from baseline as tyre age increases from lap 1 to 35+ (OLS regression slope). |
| `mv_teammate_gap` | Team per session | Qualifying single-lap delta (ms) and median clean race pace delta between teammates. |
| `mv_grid_vs_finish` | Driver per race | Starting grid position, classified finish position, and net positions gained/lost. |
| `mv_reliability` | Team per season | Total race starts, classified finishes, mechanical retirements (DNF), and completion %. |

---

## Dashboard Capabilities

### 🏁 1. Race Analysis (`1_Race_Analysis.py`)
- Official race and qualifying classifications.
- **Grid vs. Finish**: Places gained/lost interactive bar charts.
- **Stint Strategy**: Lap-by-lap tyre compound swimlanes overlaid with semi-transparent Safety Car (SC), Virtual Safety Car (VSC), and Red Flag windows.
- **Reliability Summary**: Mechanical DNF vs. accident collision breakdown by constructor.

### 📊 2. Pace Analysis (`2_Pace_Analysis.py`)
- **Clean-Lap Pace Distribution**: Interquartile range (IQR) boxplots ranking representative race pace.
- **Tyre Degradation Curves**: Compound-specific pace decay slopes (Soft vs. Medium vs. Hard) plotted against tyre age.
- **Teammate Head-to-Head**: Qualifying deltas and median race pace differentials in identical machinery.

### 🔧 3. Pit Stops & Strategy (`3_Pit_Stops.py`)
- **Pit Loss Delta**: Total time lost during pit in/out sequence relative to clean flying pace.
- **Undercut Tracker**: Automatic identification of tactical early pit stops within 3.0s windows, detailing position changes after both cars cycle through the pits.
- Explicitly marked with **`ESTIMATED`** badges to acknowledge fuel burn and traffic variances.

### ⚡ 4. Driver Telemetry (`4_Telemetry.py`)
- **Fastest Lap Overlay**: Normalized onto the uniform **10-metre spatial grid**.
- **Speed & Delta Trace**: Real-time speed comparison with circuit corner markers (T1–T14) and cumulative time delta $\Delta t(x)$.
- **Pedal Inputs**: Throttle application (0–100%), brake activation, and gear selection.
- **25 Mini-Sectors**: Track divided into 25 distance segments illustrating sectional driver dominance.
- **Corner Metrics**: Braking point distance, minimum apex speed, throttle pickup point, and corner exit speed.

---

## Engineering Rigor & Testing

- **The `ESTIMATED` Badge Standard**: Official timing transponder data (lap times, sector splits, trap speeds) are presented as pure ground truth. Derived calculations (pit loss delta, undercut pairs, resampled telemetry, corner stats) are prominently tagged with an **`ESTIMATED`** badge.
- **Automated Data Quality Suite**: [`etl/quality.py`](etl/quality.py) checks every session for missing laps, duplicate stints, and implausible lap times (&lt;50s or &gt;180s), logging anomalies into `data_quality_audit`.
- **73 Automated Unit Tests**: Comprehensive test suite run with `pytest tests/`:
  - `tests/test_clean.py`: Lap cleaning rules and edge-case status codes.
  - `tests/test_quality.py`: Anomaly detection and audit log persistence.
  - `tests/test_season.py`: Sprint weekend schedules and round order.
  - `tests/test_telemetry.py`: 10m grid interpolation, delta time integration, and corner apex statistics.

```bash
pytest tests/ -v
# 73 passed in 1.41s
```

---

## Documentation & Whitepapers

Comprehensive methodology and architectural documentation is available in the [`docs/`](docs/) directory:
- 📄 **[Du_Du_Dudu_Project_Guide.pdf](docs/Du_Du_Dudu_Project_Guide.pdf)** — Complete 4-page technical architectural guide and domain whitepaper.
- 📘 **[Methodology Guide](docs/methodology.md)** — In-depth breakdown of ETL decisions, cleaning rules, and analytical definitions.
- 📊 **[Data Dictionary](docs/data_dictionary.md)** — Complete schema reference for all database tables and views.
- 🔬 **[Empirical Findings](docs/findings.md)** — Case studies, tyre degradation slopes, and telemetry observations from the 2025 season.

---

## Repository Structure

```text
du-du-dudu/
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
│   ├── stints.py                # OpenF1 tyre compound & stint age enrichment
│   ├── telemetry.py             # 10m grid resampling, delta math & corner stats
│   ├── season.py                # Full season loader & sprint detection
│   ├── views.py                 # Materialized view refresh helper
│   └── run.py                   # Central CLI ETL runner
├── sql/
│   ├── schema.sql               # PostgreSQL tables, constraints, and indexes
│   ├── views.sql                # 7 Materialized views for heavy aggregates
│   └── analysis/                # Reference SQL queries for findings
├── docs/
│   ├── Du_Du_Dudu_Project_Guide.pdf # Complete PDF architectural whitepaper
│   ├── methodology.md           # Engineering decisions & cleaning logic
│   ├── data_dictionary.md       # Column definitions for all tables
│   └── findings.md              # Empirical findings report & insights
└── tests/                       # Complete unit test suite (73 passing tests)
```
