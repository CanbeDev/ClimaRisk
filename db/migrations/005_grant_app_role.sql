-- ClimRisk: grant app role privileges on ingestion tables (migration 005)
-- Run as the table owner (e.g. postgres) — climrisk_app has no privileges
-- to grant itself access, so this cannot be applied by the app role.

GRANT USAGE ON SCHEMA public TO climrisk_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO climrisk_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO climrisk_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO climrisk_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO climrisk_app;
