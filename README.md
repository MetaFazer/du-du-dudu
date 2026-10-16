# Du-Du-Du · F1 Analytics

> Unofficial fan project. Not affiliated with Formula 1, the FIA or any team.

A deployed Streamlit app over PostgreSQL that analyses the 2025 Formula 1 season — qualifying pace, race stints, tyre degradation, pit stop strategy, and driver telemetry.

Built as a final-year CS portfolio project (data analytics focus). The data pipeline, cleaning rules, SQL analysis, and written findings are the core deliverables, not the visual layer.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Data | FastF1 + Jolpica-F1 API |
| Database | PostgreSQL (Neon or Supabase free tier) |
| ORM | SQLAlchemy 2 + psycopg 3 |
| App | Streamlit 1.45.1 + Plotly |
| Analysis | SQL (window functions, CTEs, materialized views) + pandas |
| Tests | pytest |
| Lint | ruff |

---

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/yourname/du-du-du.git
cd du-du-du
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set your DATABASE_URL
```

`DATABASE_URL` format for Neon:
```
postgresql+psycopg://user:password@host.neon.tech/dbname?sslmode=require
```

### 3. Apply schema

```bash
python -m etl.run --schema-only
```

### 4. Load one race (Australian GP = round 1)

```bash
python -m etl.run --season 2025 --round 1
```

For a sprint weekend (e.g. round 6):
```bash
python -m etl.run --season 2025 --round 6 --sprint
```

### 5. Run the app

```bash
streamlit run app/Home.py
```

---

## Repository structure

```
du-du-du/
├── etl/
│   ├── db.py          DB connection helpers (singleton engine, apply_schema)
│   ├── clean.py       Lap cleaning rules (pure functions, fully tested)
│   ├── quality.py     DQ checks → dq_log table
│   ├── ingest.py      FastF1 + Jolpica ETL (events, sessions, drivers, laps, …)
│   └── run.py         CLI entry point
├── sql/
│   ├── schema.sql     Full PostgreSQL schema
│   ├── views.sql      Materialized views (Phase 2)
│   └── analysis/      One .sql file per finding (Phase 2)
├── app/
│   ├── Home.py        Streamlit entry point
│   ├── theme.py       Colors, CSS, Plotly template (Phase 3)
│   └── components/    Reusable Streamlit components (Phase 3)
├── tests/
│   ├── test_clean.py  Lap cleaning rule unit tests
│   └── test_quality.py DQ check unit tests
├── docs/
│   ├── methodology.md Every ETL and analysis decision documented
│   ├── data_dictionary.md Every table column explained
│   └── findings.md    Written findings (Phase 5)
├── .streamlit/
│   └── config.toml    Dark theme config
├── .env.example
├── pyproject.toml     ruff + pytest config
└── requirements.txt   Pinned dependencies
```

---

## ETL notes

- All ETL functions accept a `season` parameter — never hardcoded.
- All writes are **idempotent** (upserts / delete-then-insert per session). Re-running never duplicates rows.
- Pit stop times use **FastF1** `PitInTime`/`PitOutTime` (ms precision). Jolpica fallback is not yet implemented.
- FastF1 session load failures are caught per session, logged to `dq_log`, and skipped.
- FastF1 cache location: `FF1_CACHE_DIR` env var (default `./fastf1_cache`, gitignored).

### Lap cleaning rules (summary)
A lap is `is_clean = TRUE` only if:
1. Not an in-lap or out-lap
2. Not lap 1
3. Not under SC / VSC / Red Flag (track status codes 2–7)
4. Not on WET or INTERMEDIATE tyres
5. FastF1 marks it accurate (`IsAccurate = True`)
6. `lap_time_ms` is not null

Full rules documented in [`docs/methodology.md`](docs/methodology.md).

---

## Running tests

```bash
pytest
```

Tests are pure-function unit tests with no DB or FastF1 dependency.

---

## Derived metrics

Any metric that is not raw timing data is labeled **"estimated"** in the UI. This includes:
- Pit loss time
- Delta time between drivers
- Corner braking/throttle statistics

---

## Phases

| Phase | Status | Scope |
|---|---|---|
| 1 | ✅ Complete | Repo skeleton, schema, DB connection, ETL (one race), DQ checks, cleaning tests |
| 2 | ✅ Complete | Single/full season ETL infrastructure, materialized views, 7 SQL analyses |
| 3 | ✅ Complete | theme.py, Race Analysis, Pace Analysis, Pit Stops pages |
| 4 | ✅ Complete | 10m grid telemetry pipeline, circuit corners, corner stats, Telemetry page |
| 5 | Planned | Written findings (docs/findings.md), final insights |
| 6 | Planned | Deployment, caching review, cleanup |

---

## Disclaimer

This is an unofficial, fan-made project using publicly available data.  
Not affiliated with Formula 1, the FIA, any F1 team, or any driver.  
F1 data is sourced from FastF1 (which uses the official F1 Live Timing API) and the Jolpica-F1 open API.
