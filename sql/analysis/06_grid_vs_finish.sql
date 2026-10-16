-- =============================================================================
-- sql/analysis/06_grid_vs_finish.sql
--
-- Finding: Positions gained / lost from grid to finish
-- Metric:  finish_position − grid_position, DNFs excluded and reported separately
-- Source:  mv_grid_vs_finish
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Per-race: positions gained by driver
-- ---------------------------------------------------------------------------
SELECT
    e.round,
    e.name                                              AS race,
    d.code                                              AS driver,
    t.name                                              AS team,
    t.color_hex,
    gvf.grid,
    gvf.position                                        AS finish,
    gvf.status,
    gvf.is_dnf,
    gvf.places_gained                                   -- positive = gained places
FROM mv_grid_vs_finish gvf
JOIN sessions s  ON s.session_id = gvf.session_id
JOIN events   e  ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = gvf.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id    = en.team_id
JOIN drivers  d  ON d.driver_id  = gvf.driver_id
WHERE e.season = :season
ORDER BY e.round, gvf.places_gained DESC NULLS LAST;


-- ---------------------------------------------------------------------------
-- B. Season summary: who gained the most places on average?
--    DNFs counted separately, not included in the average.
-- ---------------------------------------------------------------------------
SELECT
    d.code                                              AS driver,
    t.name                                              AS team,
    t.color_hex,
    COUNT(*) FILTER (WHERE NOT gvf.is_dnf)              AS races_finished,
    COUNT(*) FILTER (WHERE gvf.is_dnf)                  AS dnf_count,
    ROUND(AVG(gvf.places_gained) FILTER (WHERE NOT gvf.is_dnf), 2) AS avg_places_gained,
    MAX(gvf.places_gained)                              AS best_gain,
    MIN(gvf.places_gained) FILTER (WHERE NOT gvf.is_dnf) AS worst_loss,
    -- Points scored
    SUM(r.points) FILTER (WHERE NOT gvf.is_dnf)         AS total_points
FROM mv_grid_vs_finish gvf
JOIN results  r  ON r.session_id = gvf.session_id AND r.driver_id = gvf.driver_id
JOIN sessions s  ON s.session_id = gvf.session_id
JOIN events   e  ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = gvf.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id    = en.team_id
JOIN drivers  d  ON d.driver_id  = gvf.driver_id
WHERE e.season = :season
  AND gvf.grid IS NOT NULL
GROUP BY d.code, t.name, t.color_hex
ORDER BY avg_places_gained DESC NULLS LAST;


-- ---------------------------------------------------------------------------
-- C. Starting position conversion: P1 qualifiers who won vs didn't
-- ---------------------------------------------------------------------------
SELECT
    e.season,
    COUNT(*) FILTER (WHERE gvf.grid = 1 AND gvf.position = 1) AS pole_to_win,
    COUNT(*) FILTER (WHERE gvf.grid = 1 AND gvf.position != 1
                         AND NOT gvf.is_dnf)                    AS pole_lost_win,
    COUNT(*) FILTER (WHERE gvf.grid = 1 AND gvf.is_dnf)        AS pole_dnf,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE gvf.grid = 1 AND gvf.position = 1)
        / NULLIF(COUNT(*) FILTER (WHERE gvf.grid = 1), 0),
        1
    )                                                            AS pole_conversion_pct
FROM mv_grid_vs_finish gvf
JOIN sessions s ON s.session_id = gvf.session_id
JOIN events   e ON e.event_id   = s.event_id
WHERE e.season = :season
GROUP BY e.season;
