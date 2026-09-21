-- ClimRisk: spatial basis risk decomposition on the parametric ledger (migration 010)
--
-- trigger_firings.basis_risk (payout_amount - modelled_loss) is renamed in
-- place to vertical_basis_risk: the magnitude component of basis risk — how
-- far off the payout is IN SIZE, once a payout and a modelled loss both
-- exist to compare. Two new columns capture components a single signed
-- number couldn't:
--
--   horizontal_basis_risk_flag — a KIND mismatch: TRUE when a fixed payout
--     fired against zero exposed assets (an index paid out with no real
--     exposure behind it), or when real exposure existed but this rule
--     stayed silent (a coverage gap its own conditions didn't catch).
--     Computed for every firing/evaluation, not just the overpay case.
--
--   spatial_basis_risk_pct — tiv_share/per_asset payouts only: how much of
--     the gap between a position-blind ("naive") sizing and the real,
--     distance-decayed loss (the app-layer change from Step 1, no migration
--     of its own) is attributable to *where* the exposed assets sit rather
--     than how much TIV they carry in aggregate. NULL for fixed payouts
--     (nothing spatial in a flat amount) and whenever it isn't computable.
--
-- See app/services/parametric.py's TriggerEvaluation / _spatial_basis_risk_pct
-- docstrings for the exact derivation of both.
--
-- House style follows 006-009: idempotent DDL, NUMERIC for money/ratios,
-- BOOLEAN NOT NULL DEFAULT, idx_<table>_<column> naming — no new index here
-- since neither new column is queried in isolation yet (both only ever read
-- alongside the existing hazard_event_id / trigger_id lookups).

-- ALTER ... RENAME COLUMN isn't naturally idempotent (a second run would find
-- no `basis_risk` column left to rename) — guard it so this migration is
-- still safe to re-apply, matching every other migration in this directory.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trigger_firings' AND column_name = 'basis_risk'
    ) THEN
        ALTER TABLE trigger_firings RENAME COLUMN basis_risk TO vertical_basis_risk;
    END IF;
END $$;

ALTER TABLE trigger_firings
    ADD COLUMN IF NOT EXISTS horizontal_basis_risk_flag BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS spatial_basis_risk_pct NUMERIC;

COMMENT ON COLUMN trigger_firings.vertical_basis_risk IS
    'payout_amount - modelled_loss (signed): the magnitude component of basis '
    'risk. Named basis_risk before migration 010.';
COMMENT ON COLUMN trigger_firings.horizontal_basis_risk_flag IS
    'TRUE when this firing is a KIND mismatch: a fixed payout fired against '
    'zero exposed assets, or real exposure existed but this rule stayed '
    'silent. See app/services/parametric.py:_horizontal_basis_risk_flag.';
COMMENT ON COLUMN trigger_firings.spatial_basis_risk_pct IS
    'tiv_share/per_asset only: (TIV-weighted distance-decayed PML - naive '
    'simple-average-proximity PML) / naive PML. NULL for fixed payouts and '
    'whenever not computable. See '
    'app/services/parametric.py:_spatial_basis_risk_pct.';
