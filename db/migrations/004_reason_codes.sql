-- 004_reason_codes: decisions say why. reason_code is one of three codes and agrees with the action:
--   npv_positive  -> offer
--   capital_limit -> hold (would be offered if capital were free)
--   risk_return   -> hold (not worth offering even with free capital)
-- q_hold / q_offer are the first-window values the decision compared (present-value dollars, net of the
-- capital charge). Runs published before this migration keep NULLs; every new decision must carry all three.
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('004_reason_codes');

-- NOT VALID: existing rows (runs 1-9, no reasons) are left alone; every new or updated row is checked.
ALTER TABLE decisions ADD CONSTRAINT decisions_reason CHECK (
    (reason_code IS NULL AND q_hold IS NULL AND q_offer IS NULL)
    -- reason_code IS NOT NULL is needed: `NULL IN (...)` is NULL, not false, and a CHECK passes on NULL.
    OR (reason_code IS NOT NULL AND q_hold IS NOT NULL AND q_offer IS NOT NULL AND (
        (action = 'offer' AND reason_code = 'npv_positive')
        OR (action = 'hold' AND reason_code IN ('capital_limit', 'risk_return'))))
) NOT VALID;

COMMIT;
