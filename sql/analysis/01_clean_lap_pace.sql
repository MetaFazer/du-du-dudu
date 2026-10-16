-- =============================================================================
-- sql/analysis/01_clean_lap_pace.sql
--
-- Finding: Clean-lap pace ranking per race
-- Metric:  Median and IQR of is_clean laps per driver per race session
-- Source:  mv_clean_lap_pace (materialized view)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Driver pace ranking for a specific race (parameterise :session_id)
-- ---------------------------------------------------------------------------
SELECT
    d.code                                          AS driver,
    t.name                                          AS team,
    t.color_hex,
    p.clean_lap_count,
    ROUND(p.median_ms / 1000.0, 3)                 AS median_s,
    ROUND(p.p25_ms   / 1000.0, 3)                  AS p25_s,
    ROUND(p.p75_ms   / 1000.0, 3)                  AS p75_s,
    ROUND((p.p75_ms - p.p25_ms) / 1000.0, 3)       AS iqr_s,
    ROUND(p.best_ms  / 1000.0, 3)                  AS best_s,
    ROUND(p.stddev_ms / 1000.0, 3)                 AS stddev_s,
    -- Gap to fastest driver (for waterfall charts)
    ROUND((p.median_ms - MIN(p.median_ms) OVER ()) / 1000.0, 3) AS gap_to_best_s
FROM mv_clean_lap_pace p
JOIN drivers d  ON d.driver_id = p.driver_id
JOIN sessions s ON s.session_id = p.session_id
JOIN events   e ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = p.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id   = en.team_id
WHERE p.session_id = :session_id
  AND p.clean_lap_count >= 5   -- require minimum 5 clean laps for reliability
ORDER BY p.median_ms ASC;


-- ---------------------------------------------------------------------------
-- B. Season-level pace ranking (all races, average median gap to pole)
--    Useful for: "Who was consistently fastest across the season?"
-- ---------------------------------------------------------------------------
WITH per_race AS (
    SELECT
        p.session_id,
        p.driver_id,
        p.median_ms,
        MIN(p.median_ms) OVER (PARTITION BY p.session_id) AS session_best_ms
    FROM mv_clean_lap_pace p
    JOIN sessions s ON s.session_id = p.session_id
    WHERE s.type = 'R'
      AND p.clean_lap_count >= 5
)
SELECT
    d.code                                               AS driver,
    t.name                                               AS team,
    t.color_hex,
    COUNT(*)                                             AS races_with_data,
    ROUND(AVG(pr.median_ms - pr.session_best_ms) / 1000.0, 3) AS avg_gap_to_best_s,
    ROUND(STDDEV(pr.median_ms - pr.session_best_ms) / 1000.0, 3) AS consistency_stddev_s
FROM per_race pr
JOIN drivers d  ON d.driver_id = pr.driver_id
JOIN entries  en ON en.driver_id = pr.driver_id
JOIN sessions s ON s.session_id = pr.session_id
JOIN events   e ON e.event_id   = s.event_id AND en.season = e.season
JOIN teams    t  ON t.team_id   = en.team_id
GROUP BY d.code, t.name, t.color_hex
HAVING COUNT(*) >= 3
ORDER BY avg_gap_to_best_s ASC;
