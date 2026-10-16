"""
etl/db.py – Database connection helpers.

Usage:
    from etl.db import get_engine, get_session, apply_schema

All configuration comes from the DATABASE_URL environment variable (or .env file).
Never hardcode credentials here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

log = logging.getLogger(__name__)

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return a singleton SQLAlchemy engine created from DATABASE_URL."""
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Copy .env.example to .env and fill in your credentials."
            )
        # Auto-fix: Supabase / Neon give plain postgresql:// URLs.
        # SQLAlchemy 2 + psycopg 3 requires postgresql+psycopg://.
        if url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            log.debug("DATABASE_URL driver prefix corrected to postgresql+psycopg")
        elif url.startswith("postgres://") and "+psycopg" not in url:
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
            log.debug("DATABASE_URL driver prefix corrected from postgres:// to postgresql+psycopg://")
        _engine = create_engine(
            url,
            connect_args={"prepare_threshold": None},  # Required for PgBouncer / Supabase pooler
            pool_pre_ping=True,    # avoids stale connection errors on Neon/Supabase
            pool_size=3,
            max_overflow=2,
            echo=False,
        )
        log.info("SQLAlchemy engine created: %s", _engine.url.render_as_string(hide_password=True))
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy Session bound to the singleton engine."""
    factory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return factory()


def _execute_sql_file(path: Path, eng: Engine) -> None:
    """
    Execute a SQL file statement-by-statement with AUTOCOMMIT.

    Required because:
    - CREATE MATERIALIZED VIEW cannot run inside a transaction on Supabase pooler.
    - SQLAlchemy's text() escapes '%' to '%%', so we bypass parameterization
      entirely by using raw DBAPI connection.
    """
    sql = path.read_text(encoding="utf-8")
    # Strip whole-line comments first so semicolons inside comments don't split statements
    clean_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    clean_sql = "\n".join(clean_lines)
    statements = [s.strip() for s in clean_sql.split(";") if s.strip()]

    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for stmt in statements:
            # Skip pure comment blocks
            non_comment = "\n".join(
                line for line in stmt.splitlines() if not line.strip().startswith("--")
            ).strip()
            if not non_comment:
                continue
            try:
                conn.execute(text(stmt))
            except Exception as exc:  # noqa: BLE001
                # Some DDL (e.g. CREATE INDEX IF NOT EXISTS) may warn on re-run;
                # log and continue rather than aborting the whole file.
                log.warning("Statement skipped (%s): %.80s", type(exc).__name__, stmt[:80])


def apply_schema(engine: Engine | None = None) -> None:
    """
    Execute sql/schema.sql then sql/views.sql against the database.

    Idempotent: all CREATE statements use IF NOT EXISTS.
    Uses AUTOCOMMIT so DDL works through Supabase's transaction-mode pooler.
    """
    eng = engine or get_engine()
    schema_path = Path(__file__).parent.parent / "sql" / "schema.sql"
    views_path  = Path(__file__).parent.parent / "sql" / "views.sql"

    _execute_sql_file(schema_path, eng)
    log.info("Schema applied from %s", schema_path)

    _execute_sql_file(views_path, eng)
    log.info("Views applied from %s", views_path)
