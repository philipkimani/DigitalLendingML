-- 005_reject_approved: a checker can withdraw an approved set before it goes live.
--
-- Under 002 an approved set could only become active, so an approval that turned out wrong (or a test set
-- that must never go live) stayed one click from activation forever. This adds one transition:
--
--   approved -> rejected   member of lending_checker, not the maker (records the rejecting checker and time;
--                          the earlier approval stays in the audit table)
--
-- The maker is excluded so a maker cannot undo a checker's sign-off on their own; they propose a new version.
-- Every other rule in 002 is unchanged. Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('005_reject_approved');

CREATE OR REPLACE FUNCTION parameter_sets_govern() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    who text := session_user;
    is_checker boolean := pg_has_role(session_user, 'lending_checker', 'MEMBER');
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('draft', 'proposed') THEN
            RAISE EXCEPTION 'a new parameter set starts as draft or proposed, not %', NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.maker := who;
        NEW.checker := NULL;
        NEW.checked_at := NULL;
        RETURN NEW;
    END IF;

    -- UPDATE: only status may change; the trigger fills checker/checked_at itself.
    IF to_jsonb(NEW) - '{status,checker,checked_at}'::text[] <> to_jsonb(OLD) - '{status,checker,checked_at}'::text[] THEN
        RAISE EXCEPTION 'parameter set % is immutable; create a new version', OLD.param_version
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.checker := OLD.checker;
    NEW.checked_at := OLD.checked_at;

    IF NEW.status = OLD.status THEN
        RETURN NEW;
    ELSIF OLD.status = 'draft' AND NEW.status = 'proposed' AND who = OLD.maker THEN
        RETURN NEW;
    ELSIF (OLD.status = 'proposed' AND NEW.status IN ('approved', 'rejected')
           OR OLD.status = 'approved' AND NEW.status = 'rejected')
          AND is_checker AND who <> OLD.maker THEN
        NEW.checker := who;
        NEW.checked_at := now();
        RETURN NEW;
    ELSIF (OLD.status, NEW.status) IN (('approved', 'active'), ('active', 'retired')) AND is_checker THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% may not move parameter set % from % to %', who, OLD.param_version, OLD.status, NEW.status
        USING ERRCODE = 'check_violation';
END $$;

COMMIT;
