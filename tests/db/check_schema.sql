-- Behavioural checks for the migrations + bootstrap_identity. Runs as the Entra admin in `lending` and
-- rolls back, so it leaves no data behind:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -v identity=id-digitallending-dev -f tests/db/check_schema.sql
-- Each block raises (and psql stops) if the database accepts something it must reject.

BEGIN;

CREATE FUNCTION pg_temp.must_fail(label text, sql text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE sql;
    EXCEPTION WHEN check_violation OR unique_violation OR foreign_key_violation OR not_null_violation THEN
        RAISE NOTICE 'ok: rejected %', label;
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL: accepted %', label;
END $$;

-- INSERT for the base-case parameter set with some fields overridden.
CREATE FUNCTION pg_temp.params(o jsonb DEFAULT '{}') RETURNS text LANGUAGE sql AS $$
    SELECT format(
        'INSERT INTO parameter_sets (%1$s) SELECT %1$s FROM jsonb_populate_record(NULL::parameter_sets, %2$L)',
        'status, note, checker, checked_at, n0, kappa, early, early_fee, gamma, step, lgd, m, fee, c0, c_deny,
         k_prime, k_near, k_sub, budget, disc, fixed_cost, fatigue, horizon, cycle, max_k',
        '{"status": "draft", "note": "check", "n0": 20, "kappa": 0.25, "early": 0.30, "early_fee": 0.8,
          "gamma": 0.10, "step": 0.15, "lgd": 0.65, "m": 0.04, "fee": 40, "c0": 0.02, "c_deny": 0.06,
          "k_prime": 0.08, "k_near": 0.12, "k_sub": 0.20, "budget": 250000, "disc": 0.19, "fixed_cost": 0,
          "fatigue": 0.10, "horizon": 365, "cycle": 60, "max_k": 6}'::jsonb || o)
$$;

-- The base set itself is accepted, and the database records the maker, not the client.
DO $$ BEGIN EXECUTE pg_temp.params('{"status": "proposed", "checker": "someone-else"}'); END $$;
DO $$ BEGIN
    IF (SELECT maker IS DISTINCT FROM session_user::text OR checker IS NOT NULL
        FROM parameter_sets ORDER BY param_version DESC LIMIT 1) THEN
        RAISE EXCEPTION 'FAIL: maker/checker not set by the database';
    END IF;
    RAISE NOTICE 'ok: maker recorded from the login, client-supplied checker dropped';
END $$;

-- Bounds.
SELECT pg_temp.must_fail('lgd = 65 (percent typo)', pg_temp.params('{"lgd": 65}'));
SELECT pg_temp.must_fail('kappa = 0', pg_temp.params('{"kappa": 0}'));
SELECT pg_temp.must_fail('negative budget', pg_temp.params('{"budget": -1}'));

-- Maker-checker, as enforced by the governance trigger (002).
SELECT pg_temp.must_fail('new set inserted as approved', pg_temp.params('{"status": "approved"}'));
SELECT pg_temp.must_fail('new set inserted as active', pg_temp.params('{"status": "active"}'));
SELECT pg_temp.must_fail('maker approves own set',
    'UPDATE parameter_sets SET status = ''approved'' WHERE param_version = (SELECT max(param_version) FROM parameter_sets)');
SELECT pg_temp.must_fail('editing a value after insert',
    'UPDATE parameter_sets SET lgd = 0.5 WHERE param_version = (SELECT max(param_version) FROM parameter_sets)');

-- The same rules one layer down, with the trigger off (001 constraints are the backstop if the
-- trigger is ever dropped). Rolled back with everything else.
ALTER TABLE parameter_sets DISABLE TRIGGER parameter_sets_govern;
SELECT pg_temp.must_fail('approved with no checker (constraint)', pg_temp.params('{"status": "approved"}'));
SELECT pg_temp.must_fail('maker approves own set (constraint)',
    pg_temp.params(jsonb_build_object('status', 'approved', 'checker', session_user, 'checked_at', now())));
-- Make sure one set is active (a live database already has one), so the next insert is the second.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM parameter_sets WHERE status = 'active') THEN
        EXECUTE pg_temp.params(jsonb_build_object('status', 'active', 'checker', 'someone-else', 'checked_at', now()));
    END IF;
END $$;
SELECT pg_temp.must_fail('second active set (index)',
    pg_temp.params(jsonb_build_object('status', 'active', 'checker', 'someone-else', 'checked_at', now())));
ALTER TABLE parameter_sets ENABLE TRIGGER parameter_sets_govern;

-- Runs and decisions. On a live database the current published run is superseded first (rolled back with
-- everything else); every insert below targets only the check run, data_version 'check'.
UPDATE runs SET status = 'superseded' WHERE status = 'published';
INSERT INTO runs (param_version, model_version, data_version, status, published_at)
SELECT max(param_version), 'a4b3d3a', 'check', 'published', now() FROM parameter_sets;
SELECT pg_temp.must_fail('second published run', $q$
    INSERT INTO runs (param_version, model_version, data_version, status, published_at)
    SELECT max(param_version), 'a4b3d3a', 'x', 'published', now() FROM parameter_sets $q$);
SELECT pg_temp.must_fail('model_version not a git SHA', $q$
    INSERT INTO runs (param_version, model_version, data_version) SELECT max(param_version), 'latest', 'x' FROM parameter_sets $q$);
INSERT INTO decisions (run_id, customer_id, param_version, model_version, action)
SELECT run_id, 1, param_version, model_version, 'offer' FROM runs WHERE data_version = 'check';
SELECT pg_temp.must_fail('decision versions differ from its run', $q$
    INSERT INTO decisions (run_id, customer_id, param_version, model_version, action)
    SELECT run_id, 2, param_version, 'deadbee', 'offer' FROM runs WHERE data_version = 'check' $q$);
SELECT pg_temp.must_fail('action not offer/hold', $q$
    INSERT INTO decisions (run_id, customer_id, param_version, model_version, action)
    SELECT run_id, 3, param_version, model_version, 'maybe' FROM runs WHERE data_version = 'check' $q$);

-- Customer state follows the data contract.
SELECT pg_temp.must_fail('loan above 5000', $q$
    INSERT INTO customer_state VALUES (900001, 6000, 10, 90, 0) $q$);  -- id not in use: only the range can reject it

-- Events are idempotent.
INSERT INTO events (event_id, customer_id, event_type, occurred_at) VALUES ('check-e1', 1, 'repay', now());
INSERT INTO events (event_id, customer_id, event_type, occurred_at) VALUES ('check-e1', 1, 'repay', now())
    ON CONFLICT (event_id) DO NOTHING;
DO $$ BEGIN IF (SELECT count(*) FROM events WHERE event_id = 'check-e1') <> 1 THEN RAISE EXCEPTION 'FAIL: duplicate event'; END IF; END $$;

-- Audit trail was written by the trigger.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM audit WHERE table_name = 'parameter_sets')
       OR NOT EXISTS (SELECT FROM audit WHERE table_name = 'runs') THEN
        RAISE EXCEPTION 'FAIL: audit rows missing';
    END IF;
    RAISE NOTICE 'ok: audit rows written';
END $$;

-- The managed identity has exactly the intended privileges.
SELECT set_config('check.identity', :'identity', true);
DO $$
DECLARE
    who text := current_setting('check.identity');
    want text[][] := ARRAY[
        -- table, privilege, expected
        ['customer_state', 'SELECT', 't'], ['customer_state', 'INSERT', 'f'], ['customer_state', 'UPDATE', 'f'],
        ['parameter_sets', 'SELECT', 't'], ['parameter_sets', 'INSERT', 'f'], ['parameter_sets', 'UPDATE', 'f'],
        ['events', 'INSERT', 't'], ['events', 'UPDATE', 'f'], ['events', 'DELETE', 'f'],
        ['runs', 'INSERT', 't'], ['runs', 'UPDATE', 't'], ['runs', 'DELETE', 'f'],
        ['decisions', 'INSERT', 't'], ['decisions', 'UPDATE', 'f'], ['decisions', 'DELETE', 'f'],
        ['audit', 'SELECT', 'f'], ['audit', 'INSERT', 'f'], ['audit', 'DELETE', 'f']];
    i int;
BEGIN
    IF NOT pg_has_role(who, 'lending_app', 'MEMBER') THEN RAISE EXCEPTION 'FAIL: % is not in lending_app', who; END IF;
    IF (SELECT rolsuper OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname = who) THEN
        RAISE EXCEPTION 'FAIL: % has admin attributes', who;
    END IF;
    FOR i IN 1 .. array_length(want, 1) LOOP
        IF has_table_privilege(who, want[i][1], want[i][2]) <> want[i][3]::boolean THEN
            RAISE EXCEPTION 'FAIL: % % on % should be %', who, want[i][2], want[i][1], want[i][3];
        END IF;
    END LOOP;
    RAISE NOTICE 'ok: % privileges as intended', who;
END $$;

ROLLBACK;
