-- ClimRisk: insured asset / exposure schema (migration 006)
-- Physical + financial exposure records used against hazard_events footprints
-- for spatial-financial risk queries (TIV, PML, BI loss).

CREATE TABLE IF NOT EXISTS assets (
    id                      BIGSERIAL PRIMARY KEY,

    -- Descriptive
    asset_name              TEXT,
    asset_type              TEXT,
    owner_name              TEXT,

    -- Location
    address                 TEXT,
    city                    TEXT,
    province                TEXT,
    country                 TEXT,
    iso3                    TEXT,

    -- Spatial
    location                GEOMETRY(Point, 4326) NOT NULL,

    -- Financial: values (TIV = total insured value)
    building_value          NUMERIC NOT NULL DEFAULT 0,
    contents_value          NUMERIC NOT NULL DEFAULT 0,
    total_insured_value     NUMERIC GENERATED ALWAYS AS (building_value + contents_value) STORED,

    -- Financial: business interruption parameters
    daily_net_revenue       NUMERIC,
    variable_cost_ratio     NUMERIC CHECK (variable_cost_ratio >= 0 AND variable_cost_ratio <= 1),

    -- Provenance / bookkeeping
    raw_properties          JSONB,
    first_ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assets_location ON assets USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_assets_iso3 ON assets (iso3);
CREATE INDEX IF NOT EXISTS idx_assets_asset_type ON assets (asset_type);

COMMENT ON TABLE assets IS
    'Insured asset exposure records (buildings + contents + BI parameters). '
    'Spatially joined against hazard_events footprints for PML/BI/EAL calculations.';
