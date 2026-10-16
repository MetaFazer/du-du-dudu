-- =============================================================================
-- sql/analysis/05_teammate_gap.sql
--
-- Finding: Intra-team pace gap in qualifying and race
-- Metric:  Q: best-lap delta. Race: median clean-lap difference at matched
--          tyre age (±3 laps), with approximate 95% CI via bootstrap-free
--          formula (mean ± 2*SE).
-- Source:  mv_teammate_gap + laps
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Qualifying gap: who out-qualified their teammate each round?
-- ---------------------------------------------------------------------------
SELECT
    e.season,
    e.round,
    e.name                                          AS race,
    t.name                                          AS team,
    t.color_hex,
    da.code                                         AS driver_a,
    db.code                                         AS driver_b,
    ROUND(tg.driver_a_q_ms / 1000.0, 3)            AS a_q_s,
    ROUND(tg.driver_b_q_ms / 1000.0, 3)            AS b_q_s,
    ROUND(tg.q_gap_ms      / 1000.0, 3)            AS gap_a_minus_b_s,
    CASE
        WHEN tg.q_gap_ms < 0 THEN da.code
        WHEN tg.q_gap_ms > 0 THEN db.code
        ELSE 'TIED'
    END                                             AS faster_qualifier
FROM mv_teammate_gap tg
JOIN events  e  ON e.season  = tg.season
JOIN sessions s ON s.session_id = tg.q_session_id AND s.event_id = e.event_id
JOIN teams   t  ON t.team_id = tg.team_id
JOIN drivers da ON da.driver_id = tg.driver_a_id
JOIN drivers db ON db.driver_id = tg.driver_b_id
WHERE tg.driver_a_q_ms IS NOT NULL
  AND tg.driver_b_q_ms IS NOT NULL
ORDER BY e.round, t.name;


-- ---------------------------------------------------------------------------
-- B. Season-total qualifying score: how many times each driver beat teammate
-- ---------------------------------------------------------------------------
WITH q_results AS (
    SELECT
        tg.season,
        tg.team_id,
        tg.driver_a_id,
        tg.driver_b_id,
        CASE WHEN tg.q_gap_ms < 0 THEN tg.driver_a_id ELSE tg.driver_b_id END AS faster_id,
        CASE WHEN tg.q_gap_ms > 0 THEN tg.driver_a_id ELSE tg.driver_b_id END AS slower_id
    FROM mv_teammate_gap tg
    WHERE tg.driver_a_q_ms IS NOT NULL AND tg.driver_b_q_ms IS NOT NULL
)
SELECT
    qr.season,
    t.name                                          AS team,
    d.code                                          AS driver,
    COUNT(*) FILTER (WHERE qr.faster_id = d.driver_id) AS qualifying_wins,
    COUNT(*) FILTER (WHERE qr.slower_id = d.driver_id) AS qualifying_losses,
    ROUND(
        AVG(ABS(tg.q_gap_ms)) / 1000.0, 3
    )                                               AS avg_abs_gap_s
FROM q_results qr
JOIN mv_teammate_gap tg
    ON  tg.season      = qr.season
    AND tg.team_id     = qr.team_id
    AND tg.driver_a_id = qr.driver_a_id
JOIN teams   t  ON t.team_id   = qr.team_id
JOIN drivers d  ON d.driver_id IN (qr.driver_a_id, qr.driver_b_id)
GROUP BY qr.season, t.name, d.code, d.driver_id
ORDER BY qr.season, t.name, qualifying_wins DESC;


-- ---------------------------------------------------------------------------
-- C. Race pace gap at matched tyre age (±3 laps), with standard error
--    This is more controlled than a raw race median comparison.
-- ---------------------------------------------------------------------------
WITH matched_laps AS (
    SELECT
        la.session_id,
        en_a.team_id,
        la.driver_id                            AS driver_a_id,
        lb.driver_id                            AS driver_b_id,
        la.compound,
        la.tyre_life,
        la.lap_time_ms                          AS a_ms,
        lb.lap_time_ms                          AS b_ms,
        la.lap_time_ms - lb.lap_time_ms         AS gap_ms
    FROM laps la
    JOIN laps lb
        ON  lb.session_id = la.session_id
        AND lb.compound   = la.compound
        AND ABS(lb.tyre_life - la.tyre_life) <= 3
    JOIN sessions s  ON s.session_id = la.session_id
    JOIN events   e  ON e.event_id   = s.event_id
    JOIN entries  en_a ON en_a.driver_id = la.driver_id AND en_a.season = e.season
    JOIN entries  en_b ON en_b.driver_id = lb.driver_id AND en_b.season = e.season
                       AND en_b.team_id = en_a.team_id   -- same team
    WHERE s.type       = 'R'
      AND la.is_clean  = TRUE
      AND lb.is_clean  = TRUE
      AND la.driver_id < lb.driver_id   -- avoid double-counting
      AND la.driver_id != lb.driver_id
)
SELECT
    s.session_id,
    e.round,
    e.name                                          AS race,
    t.name                                          AS team,
    da.code                                         AS driver_a,
    db.code                                         AS driver_b,
    COUNT(*)                                        AS matched_lap_pairs,
    ROUND(AVG(ml.gap_ms) / 1000.0, 3)              AS mean_gap_a_minus_b_s,
    ROUND(STDDEV(ml.gap_ms) / 1000.0, 3)           AS stddev_s,
    -- Approximate 95% CI: mean ± 2 * SE  (SE = stddev / sqrt(n))
    ROUND((AVG(ml.gap_ms) - 2 * STDDEV(ml.gap_ms) / SQRT(COUNT(*))) / 1000.0, 3) AS ci_lower_s,
    ROUND((AVG(ml.gap_ms) + 2 * STDDEV(ml.gap_ms) / SQRT(COUNT(*))) / 1000.0, 3) AS ci_upper_s
FROM matched_laps ml
JOIN sessions s ON s.session_id = ml.session_id
JOIN events   e ON e.event_id   = s.event_id
JOIN teams    t ON t.team_id    = ml.team_id
JOIN drivers  da ON da.driver_id = ml.driver_a_id
JOIN drivers  db ON db.driver_id = ml.driver_b_id
GROUP BY s.session_id, e.round, e.name, t.name, da.code, db.code
HAVING COUNT(*) >= 5
ORDER BY e.round, t.name;
