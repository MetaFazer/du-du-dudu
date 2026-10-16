-- =============================================================================
-- sql/views.sql  –  Materialized views for Du-Du-Du heavy aggregates
--
-- All views use CREATE MATERIALIZED VIEW IF NOT EXISTS so re-running is safe.
-- Each has a UNIQUE index to allow REFRESH CONCURRENTLY.
-- Pages use these views exclusively; no raw aggregate queries in Streamlit.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. Clean-lap pace per driver per session
--    Median lap time and spread for is_clean laps only.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_clean_lap_pace AS
SELECT
    l.session_id,
    l.driver_id,
    COUNT(*)                                                          AS clean_lap_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.lap_time_ms)       AS median_ms,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY l.lap_time_ms)      AS p25_ms,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY l.lap_time_ms)      AS p75_ms,
    MIN(l.lap_time_ms)                                                AS best_ms,
    STDDEV(l.lap_time_ms)                                             AS stddev_ms
FROM laps l
WHERE l.is_clean = TRUE
GROUP BY l.session_id, l.driver_id;

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_clean_lap_pace
    ON mv_clean_lap_pace (session_id, driver_id);


-- ---------------------------------------------------------------------------
-- 2. Pit loss (estimated) per driver per race session
--
--    Definition:
--      in-lap_time + out-lap_time - 2 × driver's median clean lap in that race
--
--    Caveats (shown in UI):
--      • Includes tyre warm-up and any traffic on the out-lap.
--      • Uncontrolled for fuel load difference across the stint.
--      • Labeled "estimated" everywhere in the UI.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_pit_loss AS
WITH clean_median AS (
    SELECT session_id, driver_id, median_ms
    FROM mv_clean_lap_pace
),
in_laps AS (
    -- An in-lap: pit_in_time IS NOT NULL, meaning the car pitted at end of this lap
    SELECT
        l.session_id,
        l.driver_id,
        l.lap_no,
        l.lap_time_ms AS in_lap_ms,
        l.stint
    FROM laps l
    WHERE l.pit_in_time IS NOT NULL
      AND l.lap_time_ms IS NOT NULL
),
out_laps AS (
    -- An out-lap: pit_out_time IS NOT NULL on this lap
    SELECT
        l.session_id,
        l.driver_id,
        l.lap_no,
        l.lap_time_ms AS out_lap_ms,
        l.stint
    FROM laps l
    WHERE l.pit_out_time IS NOT NULL
      AND l.lap_time_ms IS NOT NULL
),
stops AS (
    -- Match each in-lap to the subsequent out-lap (next stint)
    SELECT
        i.session_id,
        i.driver_id,
        i.lap_no             AS in_lap_no,
        o.lap_no             AS out_lap_no,
        i.in_lap_ms,
        o.out_lap_ms,
        i.in_lap_ms + o.out_lap_ms AS combined_ms
    FROM in_laps i
    JOIN out_laps o
        ON  o.session_id = i.session_id
        AND o.driver_id  = i.driver_id
        AND o.stint      = i.stint + 1   -- next stint = immediately after pit
)
SELECT
    s.session_id,
    s.driver_id,
    s.in_lap_no,
    s.out_lap_no,
    s.in_lap_ms,
    s.out_lap_ms,
    s.combined_ms,
    cm.median_ms                                              AS ref_median_ms,
    -- Pit loss estimate: combined time vs. two normal laps
    s.combined_ms - 2.0 * cm.median_ms                       AS pit_loss_ms_est,
    p.pit_lane_time_ms
FROM stops s
JOIN clean_median cm
    ON  cm.session_id = s.session_id
    AND cm.driver_id  = s.driver_id
LEFT JOIN pit_stops p
    ON  p.session_id = s.session_id
    AND p.driver_id  = s.driver_id
    AND p.lap        = s.in_lap_no;

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_pit_loss
    ON mv_pit_loss (session_id, driver_id, in_lap_no);


-- ---------------------------------------------------------------------------
-- 3. Tyre degradation – lap time vs tyre life per compound per circuit
--    Clean laps only. Fuel effect is NOT controlled (noted in UI).
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_tyre_deg AS
WITH medians AS (
    SELECT
        session_id,
        driver_id,
        compound,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lap_time_ms) AS compound_median_ms
    FROM laps
    WHERE is_clean = TRUE
      AND tyre_life IS NOT NULL
      AND compound NOT IN ('UNKNOWN', 'INTERMEDIATE', 'WET')
    GROUP BY session_id, driver_id, compound
)
SELECT
    e.circuit,
    l.session_id,
    l.driver_id,
    l.lap_no,
    l.compound,
    l.tyre_life,
    l.lap_time_ms,
    -- Normalised time: delta from driver's session median (removes absolute pace diff)
    l.lap_time_ms - m.compound_median_ms AS delta_from_median_ms
FROM laps l
JOIN medians m
    ON  m.session_id = l.session_id
    AND m.driver_id  = l.driver_id
    AND m.compound   = l.compound
JOIN sessions s ON s.session_id = l.session_id
JOIN events e   ON e.event_id   = s.event_id
WHERE l.is_clean  = TRUE
  AND l.tyre_life IS NOT NULL
  AND l.compound  NOT IN ('UNKNOWN', 'INTERMEDIATE', 'WET');

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_tyre_deg
    ON mv_tyre_deg (session_id, driver_id, lap_no);


-- ---------------------------------------------------------------------------
-- 4. Teammate gap – qualifying best lap and race median clean lap
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_teammate_gap AS
WITH q_best AS (
    -- Qualifying: best lap per driver
    SELECT
        l.session_id,
        l.driver_id,
        MIN(l.lap_time_ms) AS best_q_ms
    FROM laps l
    JOIN sessions s ON s.session_id = l.session_id
    WHERE s.type = 'Q'
      AND l.lap_time_ms IS NOT NULL
    GROUP BY l.session_id, l.driver_id
),
race_median AS (
    -- Race: median clean lap per driver
    SELECT
        session_id,
        driver_id,
        median_ms AS median_race_ms
    FROM mv_clean_lap_pace
),
pairs AS (
    -- All same-team driver pairs in each season
    SELECT
        e1.season,
        e1.driver_id AS driver_a_id,
        e2.driver_id AS driver_b_id,
        e1.team_id
    FROM entries e1
    JOIN entries e2
        ON  e2.season    = e1.season
        AND e2.team_id   = e1.team_id
        AND e2.driver_id > e1.driver_id  -- avoid duplicates
)
SELECT
    p.season,
    p.team_id,
    p.driver_a_id,
    p.driver_b_id,
    s_q.session_id                           AS q_session_id,
    qa.best_q_ms                             AS driver_a_q_ms,
    qb.best_q_ms                             AS driver_b_q_ms,
    qa.best_q_ms - qb.best_q_ms             AS q_gap_ms,       -- negative = A faster
    s_r.session_id                           AS r_session_id,
    rma.median_race_ms                       AS driver_a_race_ms,
    rmb.median_race_ms                       AS driver_b_race_ms,
    rma.median_race_ms - rmb.median_race_ms  AS race_gap_ms
FROM pairs p
JOIN events ev   ON ev.season = p.season
JOIN sessions s_q ON s_q.event_id = ev.event_id AND s_q.type = 'Q'
JOIN sessions s_r ON s_r.event_id = ev.event_id AND s_r.type = 'R'
LEFT JOIN q_best qa  ON qa.session_id = s_q.session_id AND qa.driver_id = p.driver_a_id
LEFT JOIN q_best qb  ON qb.session_id = s_q.session_id AND qb.driver_id = p.driver_b_id
LEFT JOIN race_median rma ON rma.session_id = s_r.session_id AND rma.driver_id = p.driver_a_id
LEFT JOIN race_median rmb ON rmb.session_id = s_r.session_id AND rmb.driver_id = p.driver_b_id;

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_teammate_gap
    ON mv_teammate_gap (season, team_id, driver_a_id, driver_b_id, q_session_id);


-- ---------------------------------------------------------------------------
-- 5. Grid vs finish – positions gained/lost per driver per race
--    DNFs excluded from the main figure and counted separately.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_grid_vs_finish AS
SELECT
    r.session_id,
    r.driver_id,
    r.grid,
    r.position,
    r.status,
    -- DNF if status is not 'Finished' and not '+N Lap(s)'
    CASE
        WHEN r.status = 'Finished'        THEN FALSE
        WHEN r.status LIKE '+% Lap%'      THEN FALSE
        ELSE TRUE
    END                                         AS is_dnf,
    CASE
        WHEN r.position IS NOT NULL
         AND r.grid     IS NOT NULL
         AND r.status IN ('Finished') OR r.status LIKE '+% Lap%'
        THEN r.grid - r.position   -- positive = gained places
        ELSE NULL
    END                                         AS places_gained
FROM results r
JOIN sessions s ON s.session_id = r.session_id
WHERE s.type = 'R';

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_grid_vs_finish
    ON mv_grid_vs_finish (session_id, driver_id);


-- ---------------------------------------------------------------------------
-- 6. Reliability – DNF count by team per season
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_reliability AS
SELECT
    ev.season,
    en.team_id,
    t.name                                    AS team_name,
    COUNT(*)                                  AS total_races,
    SUM(CASE WHEN gvf.is_dnf THEN 1 ELSE 0 END) AS dnf_count,
    -- Mechanical DNF: not collision / accident categories
    SUM(CASE
        WHEN gvf.is_dnf
         AND r.status NOT ILIKE '%accident%'
         AND r.status NOT ILIKE '%collision%'
         AND r.status NOT ILIKE '%spun off%'
         AND r.status NOT ILIKE '%disqualified%'
        THEN 1 ELSE 0
    END)                                      AS mechanical_dnf_count,
    SUM(CASE
        WHEN gvf.is_dnf
         AND (r.status ILIKE '%accident%'
           OR r.status ILIKE '%collision%'
           OR r.status ILIKE '%spun off%')
        THEN 1 ELSE 0
    END)                                      AS incident_dnf_count
FROM mv_grid_vs_finish gvf
JOIN results    r   ON r.session_id = gvf.session_id AND r.driver_id = gvf.driver_id
JOIN sessions   s   ON s.session_id = gvf.session_id
JOIN events     ev  ON ev.event_id  = s.event_id
JOIN entries    en  ON en.driver_id = gvf.driver_id AND en.season = ev.season
JOIN teams      t   ON t.team_id    = en.team_id
GROUP BY ev.season, en.team_id, t.name;

CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_reliability
    ON mv_reliability (season, team_id);


-- ---------------------------------------------------------------------------
-- 7. Undercut success – did pitting first within a gap gain track position?
--
--    Algorithm:
--      For each pair of cars within DEFAULT_GAP_S seconds at the start
--      of either car's in-lap, and where one pits before the other,
--      compare positions AFTER both have re-emerged from their stops.
--      Exclude any stop that overlaps a Safety Car / VSC period.
--
--    This is a best-effort approximation.  SC/VSC exclusion is based on
--    race_control messages: if any SC/VSC message exists in the lap window
--    of either stop, the pair is excluded.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_undercut AS
WITH race_laps AS (
    SELECT
        l.session_id,
        l.driver_id,
        l.lap_no,
        l.position,
        l.pit_in_time,
        l.track_status
    FROM laps l
    JOIN sessions s ON s.session_id = l.session_id
    WHERE s.type = 'R'
),
-- Identify in-lap events
in_lap_events AS (
    SELECT session_id, driver_id, lap_no AS in_lap_no, position AS pos_before_stop
    FROM race_laps
    WHERE pit_in_time IS NOT NULL
),
-- Position after stop: first lap after re-emergence (out-lap lap_no + 1)
out_lap_positions AS (
    SELECT
        l.session_id,
        l.driver_id,
        ps.stop_no,
        ps.lap             AS in_lap_no,
        -- out-lap is the next lap after pitting
        l2.lap_no          AS post_stop_lap_no,
        l2.position        AS pos_after_stop
    FROM pit_stops ps
    JOIN race_laps l
        ON  l.session_id = ps.session_id
        AND l.driver_id  = ps.driver_id
        AND l.lap_no     = ps.lap
    -- The lap after the out-lap is the first flying lap post-stop
    JOIN race_laps l2
        ON  l2.session_id = ps.session_id
        AND l2.driver_id  = ps.driver_id
        AND l2.lap_no     = ps.lap + 2   -- in-lap + out-lap + 1
),
-- Pairs of drivers within 3 seconds on the lap before either pits
-- (approximated here by within 3 positions – telemetry not available yet)
candidate_pairs AS (
    SELECT
        a.session_id,
        a.driver_id      AS driver_first,  -- pits first
        b.driver_id      AS driver_second,
        a.in_lap_no      AS first_in_lap,
        b.in_lap_no      AS second_in_lap,
        a.pos_before_stop AS first_pos_before,
        b.pos_before_stop AS second_pos_before
    FROM in_lap_events a
    JOIN in_lap_events b
        ON  b.session_id = a.session_id
        AND b.driver_id != a.driver_id
        AND b.in_lap_no  > a.in_lap_no            -- B pits later
        AND b.in_lap_no  <= a.in_lap_no + 3       -- within 3 laps
        AND ABS(a.pos_before_stop - b.pos_before_stop) <= 3  -- within 3 positions
),
-- Exclude if a SC/VSC message was active during either stop window
sc_vsc_laps AS (
    SELECT DISTINCT session_id, lap
    FROM race_control
    WHERE flag IN ('SC', 'VSC', 'SAFETY CAR', 'VIRTUAL SAFETY CAR')
       OR message ILIKE '%safety car%'
       OR message ILIKE '%virtual safety car%'
)
SELECT
    cp.session_id,
    cp.driver_first,
    cp.driver_second,
    cp.first_in_lap,
    cp.second_in_lap,
    cp.first_pos_before,
    cp.second_pos_before,
    op_a.pos_after_stop  AS first_pos_after,
    op_b.pos_after_stop  AS second_pos_after,
    -- Undercut successful if the driver who pitted first improved relative position
    CASE
        WHEN op_a.pos_after_stop IS NOT NULL
         AND op_b.pos_after_stop IS NOT NULL
         AND op_a.pos_after_stop < op_b.pos_after_stop  -- lower number = further forward
         AND cp.first_pos_before >= cp.second_pos_before  -- was equal or behind before
        THEN TRUE
        ELSE FALSE
    END AS undercut_success
FROM candidate_pairs cp
LEFT JOIN out_lap_positions op_a
    ON  op_a.session_id = cp.session_id
    AND op_a.driver_id  = cp.driver_first
    AND op_a.in_lap_no  = cp.first_in_lap
LEFT JOIN out_lap_positions op_b
    ON  op_b.session_id = cp.session_id
    AND op_b.driver_id  = cp.driver_second
    AND op_b.in_lap_no  = cp.second_in_lap
-- Exclude SC/VSC periods
WHERE NOT EXISTS (
    SELECT 1 FROM sc_vsc_laps sc
    WHERE sc.session_id = cp.session_id
      AND sc.lap BETWEEN cp.first_in_lap AND cp.second_in_lap + 1
);

DROP INDEX IF EXISTS uidx_mv_undercut;
CREATE UNIQUE INDEX IF NOT EXISTS uidx_mv_undercut
    ON mv_undercut (session_id, driver_first, driver_second, first_in_lap, second_in_lap);
