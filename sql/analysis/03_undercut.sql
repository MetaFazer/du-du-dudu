-- =============================================================================
-- sql/analysis/03_undercut.sql
--
-- Finding: Undercut success rate by circuit and team
-- Metric:  Of pairs within gap who pitted first, how many gained position?
-- Source:  mv_undercut (materialized view)
-- Caveats: Position approximated from lap data, not GPS gap. SC/VSC
--          overlapping stops are excluded. See methodology.md §6.3.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A. Overall undercut success rate for the season
-- ---------------------------------------------------------------------------
SELECT
    COUNT(*)                                                 AS total_attempts,
    SUM(CASE WHEN u.undercut_success THEN 1 ELSE 0 END)     AS successful,
    ROUND(
        100.0 * SUM(CASE WHEN u.undercut_success THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
        1
    )                                                        AS success_pct
FROM mv_undercut u
JOIN sessions s ON s.session_id = u.session_id
WHERE s.type = 'R';


-- ---------------------------------------------------------------------------
-- B. Per-circuit undercut success rate
-- ---------------------------------------------------------------------------
SELECT
    e.circuit,
    e.round,
    COUNT(*)                                                 AS attempts,
    SUM(CASE WHEN u.undercut_success THEN 1 ELSE 0 END)     AS successful,
    ROUND(
        100.0 * SUM(CASE WHEN u.undercut_success THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
        1
    )                                                        AS success_pct
FROM mv_undercut u
JOIN sessions s ON s.session_id = u.session_id
JOIN events   e ON e.event_id   = s.event_id
WHERE s.type = 'R'
GROUP BY e.circuit, e.round
HAVING COUNT(*) >= 2   -- need at least 2 attempts to be meaningful
ORDER BY success_pct DESC;


-- ---------------------------------------------------------------------------
-- C. Team undercut aggression: how often did they pit first within a gap?
-- ---------------------------------------------------------------------------
WITH all_first AS (
    SELECT
        u.session_id,
        u.driver_first AS driver_id,
        u.undercut_success
    FROM mv_undercut u
)
SELECT
    t.name                                                   AS team,
    t.color_hex,
    COUNT(*)                                                 AS times_pitted_first,
    SUM(CASE WHEN af.undercut_success THEN 1 ELSE 0 END)    AS successful_undercuts,
    ROUND(
        100.0 * SUM(CASE WHEN af.undercut_success THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
        1
    )                                                        AS success_pct
FROM all_first af
JOIN sessions s  ON s.session_id  = af.session_id
JOIN events   e  ON e.event_id    = s.event_id
JOIN entries  en ON en.driver_id  = af.driver_id AND en.season = e.season
JOIN teams    t  ON t.team_id     = en.team_id
WHERE s.type = 'R'
GROUP BY t.name, t.color_hex
ORDER BY times_pitted_first DESC;
