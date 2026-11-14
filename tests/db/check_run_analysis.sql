-- Checks for migration 009: the analysis tables refuse impossible rows, and the roles get only what they need.
-- Runs as the admin in `lending` and rolls back:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f tests/db/check_run_analysis.sql

BEGIN;

DO $$ BEGIN
    IF NOT has_table_privilege('lending_app', 'run_strategies', 'INSERT') THEN
        RAISE EXCEPTION 'FAIL: lending_app cannot write strategies';
    END IF;
    IF NOT has_table_privilege('lending_reporting', 'run_forecast', 'SELECT')
       OR has_table_privilege('lending_reporting', 'run_sensitivity', 'INSERT') THEN
        RAISE EXCEPTION 'FAIL: lending_reporting should only read the analysis tables';
    END IF;
END $$;

ALTER TABLE parameter_sets DISABLE TRIGGER parameter_sets_govern;
WITH s AS (
    INSERT INTO parameter_sets (status, note, maker, checker, checked_at, n0, kappa, early, early_fee, gamma, step,
                                lgd, m, fee, c0, c_deny, k_prime, k_near, k_sub, budget, disc, fixed_cost, fatigue,
                                horizon, cycle, max_k)
    VALUES ('approved', 'check 009', 'a', 'b', now(), 20, 0.25, 0.30, 0.8, 0.10, 0.15, 0.65, 0.04, 40,
            0.02, 0.06, 0.08, 0.12, 0.20, 250000, 0.19, 0, 0.10, 365, 60, 6)
    RETURNING param_version
), r AS (
    INSERT INTO runs (param_version, model_version, data_version)
    SELECT param_version, 'abcdef0', 'check' FROM s RETURNING run_id
)
SELECT run_id AS check_run FROM r \gset
ALTER TABLE parameter_sets ENABLE TRIGGER parameter_sets_govern;

INSERT INTO run_strategies VALUES (:check_run, 'base', 'optimal', 0.6, 14.8e6, 14.6e6, 15.0e6, 13401, 0.134, 0.226, 249999);
INSERT INTO run_forecast VALUES (:check_run, 'base', 'optimal', 1, 2000);
INSERT INTO run_sensitivity VALUES (:check_run, 'lgd', 0.5, 0.4, 6000, 249000, 17e6, 0.13);

DO $$
DECLARE run bigint := (SELECT max(run_id) FROM runs);
BEGIN
    BEGIN
        INSERT INTO run_strategies VALUES (run, 'base', 'grant_all', NULL, 15e6, 14e6, 13e6, 1, 0.1, 0.1, 1);
        RAISE EXCEPTION 'FAIL: a P5 above the P95 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO run_forecast VALUES (run, 'base', 'scorecard', 1, 10);
        RAISE EXCEPTION 'FAIL: a forecast without its strategy row was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO run_sensitivity VALUES (run, 'budget', 1, 0, 1, 1, 1, 0.1);
        RAISE EXCEPTION 'FAIL: a business lever was accepted as a sensitivity';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO run_forecast VALUES (run, 'base', 'optimal', 13, 10);
        RAISE EXCEPTION 'FAIL: month 13 was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

\echo 'check_run_analysis: all checks passed'
ROLLBACK;
