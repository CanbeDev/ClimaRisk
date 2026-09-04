-- ClimRisk: per-event ingestion error log (migration 003)

CREATE TABLE IF NOT EXISTS ingestion_errors (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT REFERENCES ingestion_runs(id),
    event_type  VARCHAR(2),
    event_id    BIGINT,
    episode_id  BIGINT,
    stage       TEXT NOT NULL,
    error_type  TEXT,
    message     TEXT NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_errors_run ON ingestion_errors (run_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_errors_created_at ON ingestion_errors (created_at DESC);

COMMENT ON TABLE ingestion_errors IS
    'Per-event failures during GDACS ingestion; does not block batch progress.';
