-- ClimRisk: PostGIS schema for GDACS hazard event storage (migration 001)
-- Run against a Postgres instance with PostGIS enabled.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS hazard_events (
    id                  BIGSERIAL PRIMARY KEY,

    -- GDACS identifiers (composite natural key for de-duplication)
    event_type          VARCHAR(2)   NOT NULL,
    event_id            BIGINT       NOT NULL,
    episode_id          BIGINT       NOT NULL,

    -- Descriptive
    event_name          TEXT,
    title               TEXT,
    description         TEXT,

    -- Alerting
    alert_level         VARCHAR(10),
    alert_score         NUMERIC,
    episode_alert_level VARCHAR(10),
    episode_alert_score NUMERIC,

    -- Severity
    severity_value      NUMERIC,
    severity_text       TEXT,
    severity_unit       TEXT,

    -- Temporal
    from_date           TIMESTAMPTZ,
    to_date             TIMESTAMPTZ,
    date_modified       TIMESTAMPTZ,
    is_current          BOOLEAN,
    is_temporary        BOOLEAN,

    -- Geographic
    country             TEXT,
    iso3                TEXT,
    glide               TEXT,
    polygon_label       TEXT,

    -- Spatial
    centroid            GEOMETRY(Point, 4326) NOT NULL,
    footprint           GEOMETRY(Geometry, 4326),

    -- Provenance / bookkeeping
    source              TEXT,
    geometry_url        TEXT,
    report_url          TEXT,
    raw_properties      JSONB,
    ingestion_source    TEXT,
    footprint_fetched_at TIMESTAMPTZ,
    first_ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_hazard_event UNIQUE (event_type, event_id, episode_id)
);

-- Idempotent column adds for databases created from the v0.1 schema.sql
ALTER TABLE hazard_events ADD COLUMN IF NOT EXISTS glide TEXT;
ALTER TABLE hazard_events ADD COLUMN IF NOT EXISTS polygon_label TEXT;
ALTER TABLE hazard_events ADD COLUMN IF NOT EXISTS footprint_fetched_at TIMESTAMPTZ;
ALTER TABLE hazard_events ADD COLUMN IF NOT EXISTS ingestion_source TEXT;

CREATE INDEX IF NOT EXISTS idx_hazard_events_centroid ON hazard_events USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_hazard_events_footprint ON hazard_events USING GIST (footprint);
CREATE INDEX IF NOT EXISTS idx_hazard_events_type ON hazard_events (event_type);
CREATE INDEX IF NOT EXISTS idx_hazard_events_alert ON hazard_events (alert_level);
CREATE INDEX IF NOT EXISTS idx_hazard_events_fromdate ON hazard_events (from_date);
CREATE INDEX IF NOT EXISTS idx_hazard_events_iso3 ON hazard_events (iso3);

CREATE INDEX IF NOT EXISTS idx_hazard_events_zaf_fromdate
    ON hazard_events (from_date DESC)
    WHERE iso3 = 'ZAF';

CREATE INDEX IF NOT EXISTS idx_hazard_events_footprint_pending
    ON hazard_events (last_seen_at)
    WHERE footprint IS NULL AND geometry_url IS NOT NULL;

COMMENT ON TABLE hazard_events IS
    'GDACS hazard events (points + polygons) polled from the GDACS API. '
    'One row per event/episode. ZAF-focused ClimRisk ingestion foundation.';
