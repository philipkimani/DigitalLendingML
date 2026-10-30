-- Checks for migration 004: a decision's reason code is known and agrees with its action, and Q-values come
-- with it. Runs as the Entra admin in `lending` and rolls back:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f tests/db/check_reasons.sql

BEGIN;

CREATE FUNCTION pg_temp.must_fail(label text, sql text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE sql;
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'ok: rejected %', label;
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL: accepted %', label;
END $$;

-- A decision row for the check run with the given action, reason and Q-values.
CREATE FUNCTION pg_temp.decision(cid int, action text, reason text, qh float8, qo float8) RETURNS text
LANGUAGE sql AS $$
    SELECT format('INSERT INTO decisions (run_id, customer_id, param_version, model_version, action, q_hold, q_offer, reason_code)
                   SELECT run_id, %s, param_version, model_version, %L, %s, %s, %L FROM runs WHERE data_version = ''check''',
                  cid, action, coalesce(qh::text, 'NULL'), coalesce(qo::text, 'NULL'), reason)
$$;

UPDATE runs SET status = 'superseded' WHERE status = 'published';
INSERT INTO runs (param_version, model_version, data_version, status, published_at)
SELECT param_version, 'a4b3d3a', 'check', 'published', now() FROM parameter_sets WHERE status = 'active';

-- Accepted: each code with its action, and the old shape (no reason, no Q-values).
DO $$ BEGIN
    EXECUTE pg_temp.decision(1, 'offer', 'npv_positive', 800, 850);
    EXECUTE pg_temp.decision(2, 'hold', 'capital_limit', 800, 790);
    EXECUTE pg_temp.decision(3, 'hold', 'risk_return', 800, 600);
    EXECUTE pg_temp.decision(4, 'hold', NULL, NULL, NULL);
    RAISE NOTICE 'ok: valid reasons and the pre-004 shape accepted';
END $$;

SELECT pg_temp.must_fail('offer with a hold reason', pg_temp.decision(5, 'offer', 'risk_return', 800, 850));
SELECT pg_temp.must_fail('hold with the offer reason', pg_temp.decision(6, 'hold', 'npv_positive', 800, 790));
SELECT pg_temp.must_fail('unknown reason', pg_temp.decision(7, 'hold', 'gut_feeling', 800, 790));
SELECT pg_temp.must_fail('reason without Q-values', pg_temp.decision(8, 'hold', 'risk_return', NULL, NULL));
SELECT pg_temp.must_fail('Q-values without a reason', pg_temp.decision(9, 'hold', NULL, 800, 790));

ROLLBACK;
