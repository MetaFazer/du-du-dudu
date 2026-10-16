-- =============================================================================
-- sql/analysis/04_tyre_deg.sql
--
-- Finding: Tyre degradation rate by compound and circuit
-- Metric:  Lap time trend vs tyre age, clean laps only
-- Source:  mv_tyre_deg (materialized view)
-- Caveats: Fuel load effect is NOT controlled. Fuel burn improves lap time
--          across a stint (roughly 0.03 s/lap/kg), which partially masks
--          tyre deg. We note this in the UI — do not claim a specific deg rate.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Average lap time by tyre life bucket for each compound at a circuit
-- ---------------------------------------------------------------------------
SELECT
    td.circuit,
    td.compound,
    -- Group tyre life into 5-lap buckets for smoothing
    (td.tyre_life / 5) * 5                                  AS tyre_life_bucket,
    COUNT(*)                                                 AS lap_count,
    ROUND(AVG(td.lap_time_ms) / 1000.0, 3)                  AS avg_lap_s,
    ROUND(AVG(td.delta_from_median_ms) / 1000.0, 3)         AS avg_delta_s,
    ROUND(STDDEV(td.delta_from_median_ms) / 1000.0, 3)      AS stddev_delta_s
FROM mv_tyre_deg td
WHERE td.circuit = :circuit
GROUP BY td.circuit, td.compound, (td.tyre_life / 5) * 5
HAVING COUNT(*) >= 3
ORDER BY td.compound, tyre_life_bucket;


-- ---------------------------------------------------------------------------
-- B. Linear degradation slope (ms per lap) using linear regression
--    This is an approximation; fuel effect is uncontrolled.
-- ---------------------------------------------------------------------------
SELECT
    td.circuit,
    td.compound,
    COUNT(*)                                                        AS lap_count,
    -- PostgreSQL linear regression built-in: REGR_SLOPE(y, x)
    ROUND(REGR_SLOPE(td.delta_from_median_ms, td.tyre_life), 2)    AS deg_slope_ms_per_lap,
    ROUND(REGR_R2(td.delta_from_median_ms, td.tyre_life), 4)       AS r_squared,
    ROUND(AVG(td.tyre_life), 1)                                     AS avg_tyre_age
FROM mv_tyre_deg td
GROUP BY td.circuit, td.compound
HAVING COUNT(*) >= 10
ORDER BY td.circuit, ABS(REGR_SLOPE(td.delta_from_median_ms, td.tyre_life)) DESC;


-- ---------------------------------------------------------------------------
-- C. Stint length distribution by compound
-- ---------------------------------------------------------------------------
SELECT
    e.circuit,
    l.compound,
    COUNT(DISTINCT (l.session_id, l.driver_id, l.stint))    AS stint_count,
    ROUND(AVG(max_tyre_life), 1)                             AS avg_stint_len,
    MIN(max_tyre_life)                                       AS shortest_stint,
    MAX(max_tyre_life)                                       AS longest_stint,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY max_tyre_life) AS median_stint
FROM (
    SELECT
        l.session_id,
        l.driver_id,
        l.stint,
        l.compound,
        MAX(l.tyre_life) AS max_tyre_life
    FROM laps l
    JOIN sessions s ON s.session_id = l.session_id
    WHERE s.type    = 'R'
      AND l.compound NOT IN ('UNKNOWN', 'INTERMEDIATE', 'WET')
      AND l.stint   IS NOT NULL
    GROUP BY l.session_id, l.driver_id, l.stint, l.compound
) sub
JOIN sessions s ON s.session_id = sub.session_id
JOIN events   e ON e.event_id   = s.event_id
GROUP BY e.circuit, sub.compound
HAVING COUNT(DISTINCT (sub.session_id, sub.driver_id, sub.stint)) >= 3
ORDER BY e.circuit, sub.compound;
