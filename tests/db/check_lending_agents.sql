-- Checks for migration 007: lending_maker may propose but not review, and run_scenarios keeps its shape.
-- Runs as the admin in `lending` and rolls back:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f tests/db/check_lending_agents.sql
-- That a new set can't start past `proposed`, and that a maker can't review, is the 002 trigger's job, tested in
-- check_schema.sql; here we check the role only holds the privileges that reach it.

BEGIN;

DO $$ BEGIN
    IF NOT has_table_privilege('lending_maker', 'parameter_sets', 'INSERT') THEN
        RAISE EXCEPTION 'FAIL: lending_maker cannot insert parameter sets';
    END IF;
    IF NOT has_table_privilege('lending_maker', 'parameter_sets', 'SELECT') THEN
        RAISE EXCEPTION 'FAIL: lending_maker cannot read parameter sets';
    END IF;
    IF has_table_privilege('lending_maker', 'parameter_sets', 'UPDATE')
       OR has_column_privilege('lending_maker', 'parameter_sets', 'status', 'UPDATE') THEN
        RAISE EXCEPTION 'FAIL: lending_maker can change a set''s status';
    END IF;
    IF NOT has_table_privilege('lending_app', 'run_scenarios', 'INSERT') THEN
        RAISE EXCEPTION 'FAIL: lending_app cannot write scenarios';
    END IF;
END $$;

ALTER TABLE parameter_sets DISABLE TRIGGER parameter_sets_govern;
WITH s AS (
    INSERT INTO parameter_sets (status, note, maker, checker, checked_at, n0, kappa, early, early_fee, gamma, step,
                                lgd, m, fee, c0, c_deny, k_prime, k_near, k_sub, budget, disc, fixed_cost, fatigue,
                                horizon, cycle, max_k)
    VALUES ('approved', 'check 007', 'a', 'b', now(), 20, 0.25, 0.30, 0.8, 0.10, 0.15, 0.65, 0.04, 40,
            0.02, 0.06, 0.08, 0.12, 0.20, 250000, 0.19, 0, 0.10, 365, 60, 6)
    RETURNING param_version
), r AS (
    INSERT INTO runs (param_version, model_version, data_version)
    SELECT param_version, 'abcdef0', 'check' FROM s RETURNING run_id
)
SELECT run_id AS check_run FROM r \gset
ALTER TABLE parameter_sets ENABLE TRIGGER parameter_sets_govern;

INSERT INTO run_scenarios VALUES (:check_run, 'budget', 300000, 0.5, 100, 290000, 1000000, 0.1);

DO $$ BEGIN
    BEGIN
        INSERT INTO run_scenarios SELECT run_id, 'lgd', 0.3, 0.5, 100, 290000, 1000000, 0.1 FROM run_scenarios LIMIT 1;
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'ok: rejected a lever outside the list';
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL: accepted a lever outside the list';
END $$;

ROLLBACK;
