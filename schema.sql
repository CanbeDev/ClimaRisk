-- ClimRisk: full schema bootstrap (runs all migrations in order)
-- Usage: psql climrisk -f schema.sql

\i db/migrations/001_hazard_events.sql
\i db/migrations/002_ingestion_runs.sql
\i db/migrations/003_ingestion_errors.sql
\i db/migrations/004_affected_countries.sql
\i db/migrations/005_grant_app_role.sql
\i db/migrations/006_assets.sql
\i db/migrations/007_insured_value.sql
\i db/migrations/008_parametric_triggers.sql
\i db/migrations/009_global_events.sql
\i db/migrations/010_spatial_basis_risk.sql
