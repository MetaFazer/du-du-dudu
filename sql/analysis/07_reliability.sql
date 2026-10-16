-- =============================================================================
-- sql/analysis/07_reliability.sql
--
-- Finding: Team reliability – DNF rate and causes
-- Metric:  DNFs by team, split into mechanical vs incident
-- Source:  mv_reliability
-- Note:    Classification (mechanical vs incident) uses Jolpica status strings.
--          Some statuses are ambiguous (e.g. "Retired" with no reason).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Season reliability table
-- ---------------------------------------------------------------------------
SELECT
    r.season,
    r.team_name                                         AS team,
    t.color_hex,
    r.total_races,
    r.dnf_count,
    r.mechanical_dnf_count,
    r.incident_dnf_count,
    r.dnf_count - r.mechanical_dnf_count
        - r.incident_dnf_count                         AS other_dnf_count,
    ROUND(100.0 * r.dnf_count / NULLIF(r.total_races, 0), 1) AS dnf_pct,
    ROUND(100.0 * r.mechanical_dnf_count / NULLIF(r.total_races, 0), 1) AS mechanical_pct
FROM mv_reliability r
JOIN teams t ON t.team_id = r.team_id
WHERE r.season = :season
ORDER BY r.dnf_count DESC;


-- ---------------------------------------------------------------------------
-- B. DNF reasons detail – what status strings appear most often?
-- ---------------------------------------------------------------------------
SELECT
    e.season,
    t.name                                              AS team,
    t.color_hex,
    gvf.status,
    COUNT(*)                                            AS occurrences
FROM mv_grid_vs_finish gvf
JOIN results  r  ON r.session_id = gvf.session_id AND r.driver_id = gvf.driver_id
JOIN sessions s  ON s.session_id = gvf.session_id
JOIN events   e  ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = gvf.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id    = en.team_id
WHERE gvf.is_dnf = TRUE
  AND e.season   = :season
GROUP BY e.season, t.name, t.color_hex, gvf.status
ORDER BY occurrences DESC;


-- ---------------------------------------------------------------------------
-- C. Points lost to DNF (estimated as avg points for finishing position)
--    Based on the standard 25-18-15-12-10-8-6-4-2-1 points system.
-- ---------------------------------------------------------------------------
WITH points_scale (pos, pts) AS (
    VALUES (1,25),(2,18),(3,15),(4,12),(5,10),(6,8),(7,6),(8,4),(9,2),(10,1)
),
dnf_laps AS (
    -- Approximate race position at time of DNF: last recorded position
    SELECT
        gvf.session_id,
        gvf.driver_id,
        gvf.status,
        -- Use the last lap's position as a proxy for where they retired
        LAST_VALUE(l.position) OVER (
            PARTITION BY l.session_id, l.driver_id
            ORDER BY l.lap_no
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS retirement_position
    FROM mv_grid_vs_finish gvf
    JOIN laps l ON l.session_id = gvf.session_id AND l.driver_id = gvf.driver_id
    WHERE gvf.is_dnf = TRUE
)
SELECT
    e.season,
    d.code                                              AS driver,
    t.name                                              AS team,
    COUNT(*)                                            AS dnf_count,
    COALESCE(SUM(ps.pts), 0)                           AS actual_points,
    -- If they had finished at their retirement position, roughly what would they score?
    SUM(COALESCE(ps2.pts, 0))                          AS estimated_finish_points
FROM dnf_laps dl
JOIN sessions s  ON s.session_id = dl.session_id
JOIN events   e  ON e.event_id   = s.event_id
JOIN entries  en ON en.driver_id = dl.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id    = en.team_id
JOIN drivers  d  ON d.driver_id  = dl.driver_id
JOIN results  r  ON r.session_id = dl.session_id AND r.driver_id = dl.driver_id
LEFT JOIN points_scale ps  ON ps.pos = r.position
LEFT JOIN points_scale ps2 ON ps2.pos = dl.retirement_position
WHERE e.season = :season
GROUP BY e.season, d.code, t.name
ORDER BY dnf_count DESC;
