-- ClimRisk: parametric trigger rules engine (migration 008, Build Order Step 7 / Phase 2)
--
-- Parametric (index-based) cover pays a PREDEFINED amount when a MEASURABLE
-- condition is met — no loss adjustment. Two tables:
--
--   parametric_triggers  — rule definitions (conditions + payout formula)
--   trigger_firings      — the current set of rules that HAVE fired against a
--                          hazard event, with the payout and the basis risk
--                          (payout minus the modelled PML loss)
--
-- trigger_firings holds only rules that currently fire: the engine upserts a
-- row when a rule fires and deletes it when re-evaluation shows it no longer
-- does, so the table always reads as "outstanding parametric payouts", not an
-- evaluation log. Non-firing evaluations are returned by the API on demand,
-- not persisted. House style follows 006/007: idempotent DDL, BIGSERIAL keys,
-- TIMESTAMPTZ, NUMERIC for money, idx_<table>_<column> names.
--
-- Grants: climrisk_app inherits SELECT/INSERT/UPDATE/DELETE automatically from
-- the ALTER DEFAULT PRIVILEGES in 005, as long as this migration is applied by
-- the same admin role that applied 005 (the table owner).

CREATE TABLE IF NOT EXISTS parametric_triggers (
    id                       BIGSERIAL PRIMARY KEY,
    name                     TEXT NOT NULL UNIQUE,
    description              TEXT,
    is_active                BOOLEAN NOT NULL DEFAULT TRUE,

    -- Conditions. Every non-NULL column here must hold for the rule to fire;
    -- a NULL condition is "don't care".
    event_type               TEXT,                       -- GDACS code (EQ/TC/FL/...), NULL = any
    min_alert_level          TEXT CHECK (min_alert_level IN ('Green', 'Orange', 'Red')),
    min_severity_value       NUMERIC,                    -- floor on hazard_events.severity_value
    severity_unit            TEXT,                       -- documentation only; GDACS units vary by hazard
    iso3                     TEXT,                       -- country the event must affect; NULL = configured country at eval time
    requires_exposed_assets  BOOLEAN NOT NULL DEFAULT TRUE,  -- TRUE = only fire if >=1 asset intersects the footprint

    -- Payout formula.
    payout_kind              TEXT NOT NULL DEFAULT 'fixed'
                             CHECK (payout_kind IN ('fixed', 'per_asset', 'tiv_share')),
    payout_value             NUMERIC NOT NULL CHECK (payout_value >= 0),
                             -- fixed:     flat currency amount
                             -- per_asset: amount per intersecting asset
                             -- tiv_share: fraction (0..1) of exposed TIV
    payout_currency          TEXT NOT NULL DEFAULT 'ZAR',

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parametric_triggers_active
    ON parametric_triggers (is_active) WHERE is_active;

COMMENT ON TABLE parametric_triggers IS
    'Parametric insurance rule definitions: measurable conditions on a hazard '
    'event plus a payout formula. Evaluated by app/services/parametric.py.';


CREATE TABLE IF NOT EXISTS trigger_firings (
    id                    BIGSERIAL PRIMARY KEY,
    trigger_id            BIGINT NOT NULL REFERENCES parametric_triggers (id) ON DELETE CASCADE,
    hazard_event_id       BIGINT NOT NULL REFERENCES hazard_events (id) ON DELETE CASCADE,

    reason                TEXT,                          -- human-readable "fired because ..."
    exposed_asset_count   INTEGER NOT NULL DEFAULT 0,
    exposed_tiv           NUMERIC NOT NULL DEFAULT 0,    -- Σ TIV of intersecting assets
    modelled_loss         NUMERIC NOT NULL DEFAULT 0,    -- PML from the intersection service
    payout_amount         NUMERIC NOT NULL DEFAULT 0,
    basis_risk            NUMERIC NOT NULL DEFAULT 0,    -- payout_amount − modelled_loss (signed)
    payout_currency       TEXT NOT NULL DEFAULT 'ZAR',

    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One row per (rule, event): the ON CONFLICT target for idempotent re-evaluation.
    UNIQUE (trigger_id, hazard_event_id)
);

CREATE INDEX IF NOT EXISTS idx_trigger_firings_hazard_event_id ON trigger_firings (hazard_event_id);
CREATE INDEX IF NOT EXISTS idx_trigger_firings_trigger_id ON trigger_firings (trigger_id);

COMMENT ON TABLE trigger_firings IS
    'Parametric rules that currently fire against a hazard event: payout amount '
    'and basis risk (payout − modelled PML loss). Rows are removed when '
    're-evaluation shows the rule no longer fires, so this is a live payout '
    'ledger, not an evaluation history.';
