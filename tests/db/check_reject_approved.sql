-- Checks for migration 005: a checker who is not the maker can reject an approved set; nobody else can, and a
-- rejected set goes nowhere. Runs as the Entra admin in `lending` and rolls back:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f tests/db/check_reject_approved.sql
-- The trigger reads session_user, which a non-superuser cannot change, so the "other person" is simulated:
-- approved rows are inserted with the trigger off (maker/checker written directly). The admin is a member of
-- lending_checker because it created the role (PostgreSQL 16 grants that, recorded by the server, so the admin
-- cannot revoke it); the non-checker refusal shares its condition with 002's branch and is not re-tested here.

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

-- An approved set made by `maker_name`, approved by `checker_name`; returns its version.
CREATE FUNCTION pg_temp.approved(maker_name text, checker_name text) RETURNS int LANGUAGE sql AS $$
    INSERT INTO parameter_sets (status, note, maker, checker, checked_at, n0, kappa, early, early_fee, gamma, step,
                                lgd, m, fee, c0, c_deny, k_prime, k_near, k_sub, budget, disc, fixed_cost, fatigue,
                                horizon, cycle, max_k)
    VALUES ('approved', 'check 005', maker_name, checker_name, now(), 20, 0.25, 0.30, 0.8, 0.10, 0.15, 0.65, 0.04, 40,
            0.02, 0.06, 0.08, 0.12, 0.20, 250000, 0.19, 0, 0.10, 365, 60, 6)
    RETURNING param_version
$$;

DO $$ BEGIN
    IF NOT pg_has_role(session_user, 'lending_checker', 'MEMBER') THEN
        RAISE EXCEPTION 'precondition: % is not a member of lending_checker', session_user;
    END IF;
END $$;

CREATE TEMP TABLE v (by_other int, by_me int);
ALTER TABLE parameter_sets DISABLE TRIGGER parameter_sets_govern;
INSERT INTO v SELECT pg_temp.approved('someone-else', 'checker-a'), pg_temp.approved(session_user, 'checker-a');
ALTER TABLE parameter_sets ENABLE TRIGGER parameter_sets_govern;

-- Accepted: a checker who is not the maker rejects an approved set, and is recorded as its checker.
UPDATE parameter_sets SET status = 'rejected' WHERE param_version = (SELECT by_other FROM v);
DO $$ BEGIN
    IF (SELECT checker IS DISTINCT FROM session_user::text OR checked_at <> now()
        FROM parameter_sets WHERE param_version = (SELECT by_other FROM v)) THEN
        RAISE EXCEPTION 'FAIL: rejecting checker not recorded';
    END IF;
    RAISE NOTICE 'ok: checker rejected an approved set and was recorded';
END $$;

-- Refused.
SELECT pg_temp.must_fail('maker rejects their own approved set',
    format('UPDATE parameter_sets SET status = ''rejected'' WHERE param_version = %s', (SELECT by_me FROM v)));
SELECT pg_temp.must_fail('rejected set activated',
    format('UPDATE parameter_sets SET status = ''active'' WHERE param_version = %s', (SELECT by_other FROM v)));
SELECT pg_temp.must_fail('rejected set re-approved',
    format('UPDATE parameter_sets SET status = ''approved'' WHERE param_version = %s', (SELECT by_other FROM v)));

ROLLBACK;
