-- ClimRisk: declared insured value for Protection Gap (migration 007)
-- Adds the client-declared amount actually insured per asset. Distinct from
-- assets.total_insured_value (TIV — the full building+contents replacement
-- value, a ceiling): insured_value can be lower than TIV (underinsurance) or
-- 0/NULL (uninsured). Protection Gap = TIV exposure at risk minus this value,
-- per ClimRisk Master Document Section 4.5.

ALTER TABLE assets ADD COLUMN IF NOT EXISTS insured_value NUMERIC
    CHECK (insured_value >= 0);

COMMENT ON COLUMN assets.insured_value IS
    'Client-declared amount actually insured for this asset (NULL/0 = uninsured '
    'or not yet declared). Distinct from total_insured_value (TIV, the full '
    'replacement-value ceiling) — insured_value can be lower due to '
    'underinsurance. Used for Protection Gap = TIV exposure at risk minus '
    'declared insured value (see app/services/intersection.py).';
