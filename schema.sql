-- ClimRisk: full schema bootstrap (runs all migrations in order)
-- Usage: psql climrisk -f schema.sql

\i db/migrations/001_hazard_events.sql
\i db/migrations/002_ingestion_runs.sql
\i db/migrations/003_ingestion_errors.sql
\i db/migrations/004_affected_countries.sql
