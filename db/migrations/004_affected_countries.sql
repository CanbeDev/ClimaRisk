-- Preserve every country affected by a regional GDACS event, not only its primary ISO3.

ALTER TABLE hazard_events
    ADD COLUMN IF NOT EXISTS affected_countries TEXT[];

CREATE INDEX IF NOT EXISTS idx_hazard_events_affected_countries
    ON hazard_events USING GIN (affected_countries);
