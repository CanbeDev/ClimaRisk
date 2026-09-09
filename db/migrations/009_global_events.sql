-- ClimRisk: global event storage — indexing adjustment (migration 009)
--
-- Ingestion no longer discards non-ZAF GDACS events (event_affects_country was
-- removed from process_features). `hazard_events` is now a worldwide table,
-- substantially larger than the SA-only volume it held before.
--
-- Nothing else changes: assets are South-African only, and every
-- financial/exposure query is country-scoped in SQL —
--   /hazards (default), /trends/hazards, evaluate_all_events,
--   fetch_pending_polygons  →  WHERE iso3 = %s OR %s = ANY(affected_countries)
--   run_intersection        →  per-footprint against SA-only assets
-- so a foreign event is stored but never reaches a SA-scoped view.
--
-- The country predicate is already well indexed:
--   idx_hazard_events_iso3               (btree, 001)  — the `iso3 = %s` half
--   idx_hazard_events_affected_countries (GIN,   004)  — the array half
-- Postgres BitmapOrs the two. This migration only cleans up one now-unusable
-- index and adds a recency composite for the larger table.

-- The ZAF-hardcoded partial index can never serve the queries the app runs:
-- a partial index needs its literal predicate (`iso3 = 'ZAF'`) to appear in
-- the query, but every query filters on a bind parameter. Drop it.
DROP INDEX IF EXISTS idx_hazard_events_zaf_fromdate;

-- Plain composite for the `iso3 = %s` access path, newest first — replaces the
-- partial index above and stays useful whatever GDACS_COUNTRY_FILTER is set to.
CREATE INDEX IF NOT EXISTS idx_hazard_events_iso3_fromdate
    ON hazard_events (iso3, from_date DESC);

COMMENT ON TABLE hazard_events IS
    'GDACS hazard events (points + polygons), worldwide. One row per '
    'event/episode. Country scoping for ClimRisk''s SA-focused financial '
    'views happens in the read queries, not at ingestion.';
