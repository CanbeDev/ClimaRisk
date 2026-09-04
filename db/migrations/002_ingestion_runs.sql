-- ClimRisk: ingestion run audit log (migration 002)

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id              BIGSERIAL PRIMARY KEY,
    job_type        TEXT NOT NULL,
    status          TEXT NOT NULL,
    source_endpoint TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    events_fetched  INT DEFAULT 0,
    events_upserted INT DEFAULT 0,
    events_skipped  INT DEFAULT 0,
    events_failed   INT DEFAULT 0,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started_at
    ON ingestion_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_job_type
    ON ingestion_runs (job_type, started_at DESC);

COMMENT ON TABLE ingestion_runs IS
    'Operational audit log for scheduled and manual GDACS ingestion jobs.';
