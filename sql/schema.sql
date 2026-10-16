-- =============================================================================
-- Du-Du-Du F1 Analytics – schema.sql
-- PostgreSQL schema for the full analytics database.
-- All ETL writes are idempotent (upserts / delete-and-reload per session).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Reference / dimension tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS events (
    event_id   SERIAL PRIMARY KEY,
    season     INTEGER      NOT NULL,
    round      INTEGER      NOT NULL,
    name       TEXT         NOT NULL,
    circuit    TEXT         NOT NULL,
    country    TEXT         NOT NULL,
    date       DATE         NOT NULL,
    UNIQUE (season, round)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id SERIAL PRIMARY KEY,
    event_id   INTEGER      NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    type       TEXT         NOT NULL  -- 'Q', 'R', 'Sprint', 'SQ'
    ,UNIQUE (event_id, type)
);

CREATE TABLE IF NOT EXISTS drivers (
    driver_id  SERIAL PRIMARY KEY,
    code       CHAR(3)      NOT NULL UNIQUE,  -- e.g. 'VER'
    full_name  TEXT         NOT NULL,
    number     INTEGER      NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS teams (
    team_id    SERIAL PRIMARY KEY,
    name       TEXT         NOT NULL UNIQUE,
    color_hex  CHAR(7)      NOT NULL  -- '#rrggbb'
);

CREATE TABLE IF NOT EXISTS entries (
    season     INTEGER      NOT NULL,
    driver_id  INTEGER      NOT NULL REFERENCES drivers(driver_id),
    team_id    INTEGER      NOT NULL REFERENCES teams(team_id),
    PRIMARY KEY (season, driver_id)
);

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS results (
    result_id  SERIAL PRIMARY KEY,
    session_id INTEGER      NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    driver_id  INTEGER      NOT NULL REFERENCES drivers(driver_id),
    grid       INTEGER,
    position   INTEGER,
    status     TEXT,
    points     NUMERIC(6,2),
    UNIQUE (session_id, driver_id)
);

-- ---------------------------------------------------------------------------
-- Lap data  (core fact table)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS laps (
    lap_id          BIGSERIAL    PRIMARY KEY,
    session_id      INTEGER      NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    driver_id       INTEGER      NOT NULL REFERENCES drivers(driver_id),
    lap_no          SMALLINT     NOT NULL,
    lap_time_ms     INTEGER,       -- NULL means lap time unavailable
    s1_ms           INTEGER,
    s2_ms           INTEGER,
    s3_ms           INTEGER,
    compound        TEXT,          -- 'SOFT','MEDIUM','HARD','INTERMEDIATE','WET','UNKNOWN'
    tyre_life       SMALLINT,      -- laps on this set
    stint           SMALLINT,
    pit_in_time     BIGINT,        -- milliseconds from session start
    pit_out_time    BIGINT,
    track_status    TEXT,          -- FastF1 track status string
    position        SMALLINT,
    is_accurate     BOOLEAN        NOT NULL DEFAULT FALSE,
    is_clean        BOOLEAN        NOT NULL DEFAULT FALSE,
    UNIQUE (session_id, driver_id, lap_no)
);

CREATE INDEX IF NOT EXISTS idx_laps_session_driver ON laps (session_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_laps_session_driver_lap ON laps (session_id, driver_id, lap_no);
CREATE INDEX IF NOT EXISTS idx_laps_is_clean ON laps (session_id, is_clean) WHERE is_clean = TRUE;

-- ---------------------------------------------------------------------------
-- Pit stops
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pit_stops (
    pit_stop_id     SERIAL       PRIMARY KEY,
    session_id      INTEGER      NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    driver_id       INTEGER      NOT NULL REFERENCES drivers(driver_id),
    stop_no         SMALLINT     NOT NULL,
    lap             SMALLINT     NOT NULL,
    pit_lane_time_ms INTEGER,     -- NULL when data unavailable
    UNIQUE (session_id, driver_id, stop_no)
);

CREATE INDEX IF NOT EXISTS idx_pit_stops_session ON pit_stops (session_id);

-- ---------------------------------------------------------------------------
-- Race control messages
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS race_control (
    rc_id      BIGSERIAL    PRIMARY KEY,
    session_id INTEGER      NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    time       BIGINT       NOT NULL,   -- milliseconds from session start
    lap        SMALLINT,
    category   TEXT,                    -- 'Flag', 'SafetyCar', 'DRS', etc.
    flag       TEXT,                    -- 'GREEN','YELLOW','RED','SC','VSC', etc.
    message    TEXT         NOT NULL,
    UNIQUE (session_id, time, message)
);

CREATE INDEX IF NOT EXISTS idx_race_control_session ON race_control (session_id);

-- ---------------------------------------------------------------------------
-- Weather samples
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS weather (
    weather_id  BIGSERIAL   PRIMARY KEY,
    session_id  INTEGER     NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    time        BIGINT      NOT NULL,  -- milliseconds from session start
    air_temp    NUMERIC(5,2),
    track_temp  NUMERIC(5,2),
    rainfall    BOOLEAN,
    UNIQUE (session_id, time)
);

CREATE INDEX IF NOT EXISTS idx_weather_session ON weather (session_id);

-- ---------------------------------------------------------------------------
-- Telemetry (resampled 10-m grid, one row per grid point)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS telemetry_lap (
    telem_id   BIGSERIAL    PRIMARY KEY,
    session_id INTEGER      NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    driver_id  INTEGER      NOT NULL REFERENCES drivers(driver_id),
    lap_no     SMALLINT     NOT NULL,
    dist_m     NUMERIC(8,2) NOT NULL,  -- distance from lap start in metres
    speed      NUMERIC(6,2),
    throttle   NUMERIC(5,2),           -- 0–100 %
    brake      BOOLEAN,
    gear       SMALLINT,
    rpm        INTEGER,
    drs        SMALLINT,               -- FastF1 DRS channel integer
    x          NUMERIC(12,4),          -- map coordinate
    y          NUMERIC(12,4),
    UNIQUE (session_id, driver_id, lap_no, dist_m)
);

CREATE INDEX IF NOT EXISTS idx_telem_session_driver_lap ON telemetry_lap (session_id, driver_id, lap_no);

-- ---------------------------------------------------------------------------
-- Circuit corners
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS corners (
    corner_id  SERIAL       PRIMARY KEY,
    circuit    TEXT         NOT NULL,
    corner_no  SMALLINT     NOT NULL,
    dist_m     NUMERIC(8,2) NOT NULL,
    x          NUMERIC(12,4),
    y          NUMERIC(12,4),
    UNIQUE (circuit, corner_no)
);

-- ---------------------------------------------------------------------------
-- Corner statistics (computed from telemetry)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS corner_stats (
    cs_id              BIGSERIAL  PRIMARY KEY,
    session_id         INTEGER    NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    driver_id          INTEGER    NOT NULL REFERENCES drivers(driver_id),
    lap_no             SMALLINT   NOT NULL,
    corner_no          SMALLINT   NOT NULL,
    brake_point_m      NUMERIC(8,2),    -- dist_m where brake first turns on before corner
    min_speed          NUMERIC(6,2),    -- lowest speed within the corner window
    throttle_pickup_m  NUMERIC(8,2),    -- dist_m where throttle first exceeds threshold after apex
    exit_speed         NUMERIC(6,2),    -- speed at the end of the corner window
    UNIQUE (session_id, driver_id, lap_no, corner_no)
);

CREATE INDEX IF NOT EXISTS idx_cs_session_driver_lap ON corner_stats (session_id, driver_id, lap_no);

-- ---------------------------------------------------------------------------
-- Data quality log
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dq_log (
    log_id      BIGSERIAL   PRIMARY KEY,
    run_id      TEXT        NOT NULL,   -- UUID or timestamp string for the ETL run
    table_name  TEXT        NOT NULL,
    check_name  TEXT        NOT NULL,
    severity    TEXT        NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR')),
    row_count   INTEGER,
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dq_log_run ON dq_log (run_id);
