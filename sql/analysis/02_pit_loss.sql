-- =============================================================================
-- sql/analysis/02_pit_loss.sql
--
-- Finding: Estimated pit loss time by driver and team
-- Metric:  (in-lap + out-lap) − 2 × median clean lap time  [ESTIMATED]
-- Source:  mv_pit_loss (materialized view)
-- UI note: Always label this metric "estimated" – includes tyre warm-up,
--          traffic on out-lap, and uncontrolled fuel load effect.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Per-stop pit loss detail for one race
-- ---------------------------------------------------------------------------
SELECT
    d.code                                              AS driver,
    t.name                                              AS team,
    t.color_hex,
    pl.in_lap_no,
    pl.out_lap_no,
    ROUND(pl.in_lap_ms    / 1000.0, 3)                 AS in_lap_s,
    ROUND(pl.out_lap_ms   / 1000.0, 3)                 AS out_lap_s,
    ROUND(pl.ref_median_ms / 1000.0, 3)                AS ref_median_s,
    ROUND(pl.pit_loss_ms_est / 1000.0, 3)              AS pit_loss_est_s,   -- ESTIMATED
    ROUND(pl.pit_lane_time_ms / 1000.0, 3)             AS pit_lane_time_s   -- from FastF1
FROM mv_pit_loss pl
JOIN drivers d  ON d.driver_id = pl.driver_id
JOIN sessions s ON s.session_id = pl.session_id
JOIN events   e ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = pl.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id    = en.team_id
WHERE pl.session_id = :session_id
ORDER BY pl.pit_loss_ms_est DESC;


-- ---------------------------------------------------------------------------
-- B. Average pit loss by team across the season (estimated)
-- ---------------------------------------------------------------------------
SELECT
    t.name                                              AS team,
    t.color_hex,
    COUNT(*)                                            AS stop_count,
    ROUND(AVG(pl.pit_loss_ms_est)  / 1000.0, 3)       AS avg_pit_loss_est_s,
    ROUND(MIN(pl.pit_loss_ms_est)  / 1000.0, 3)       AS min_pit_loss_est_s,
    ROUND(MAX(pl.pit_loss_ms_est)  / 1000.0, 3)       AS max_pit_loss_est_s,
    ROUND(STDDEV(pl.pit_loss_ms_est) / 1000.0, 3)     AS stddev_pit_loss_s,
    ROUND(AVG(pl.pit_lane_time_ms) / 1000.0, 3)       AS avg_pit_lane_s
FROM mv_pit_loss pl
JOIN sessions s  ON s.session_id  = pl.session_id
JOIN events   e  ON e.event_id    = s.event_id
JOIN entries  en ON en.driver_id  = pl.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id     = en.team_id
WHERE s.type = 'R'
  AND pl.pit_loss_ms_est IS NOT NULL
  AND pl.pit_loss_ms_est BETWEEN -10000 AND 60000   -- exclude implausible outliers
GROUP BY t.name, t.color_hex
ORDER BY avg_pit_loss_est_s ASC;


-- ---------------------------------------------------------------------------
-- C. Pit stop time (pit lane only) by team – uses FastF1 PitInTime/PitOutTime
-- ---------------------------------------------------------------------------
SELECT
    t.name                                              AS team,
    t.color_hex,
    COUNT(*)                                            AS stop_count,
    ROUND(AVG(ps.pit_lane_time_ms)  / 1000.0, 3)      AS avg_pit_lane_s,
    ROUND(MIN(ps.pit_lane_time_ms)  / 1000.0, 3)      AS fastest_stop_s,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
          (ORDER BY ps.pit_lane_time_ms) / 1000.0, 3)  AS median_stop_s
FROM pit_stops ps
JOIN sessions s  ON s.session_id  = ps.session_id
JOIN events   e  ON e.event_id    = s.event_id
JOIN entries  en ON en.driver_id  = ps.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id     = en.team_id
WHERE s.type = 'R'
  AND ps.pit_lane_time_ms IS NOT NULL
  AND ps.pit_lane_time_ms BETWEEN 10000 AND 120000  -- 10 s – 120 s sanity bounds
GROUP BY t.name, t.color_hex
ORDER BY avg_pit_lane_s ASC;
