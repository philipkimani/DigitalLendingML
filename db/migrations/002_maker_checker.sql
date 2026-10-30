-- 002_maker_checker: the database, not the client, decides who made and who checked a parameter set.
--
-- 001 stored maker and checker as client-supplied text, so a caller could type someone else's name
-- as checker. Here a trigger sets both from session_user (the authenticated login, which SET ROLE
-- cannot change) and allows only these status transitions:
--
--   draft    -> proposed            maker only
--   proposed -> approved | rejected member of lending_checker, not the maker (records checker, checked_at)
--   approved -> active              member of lending_checker (retire the current active set first,
--   active   -> retired             in the same transaction: the one-active index enforces it)
--
-- Parameter values are immutable after insert: a change is a new param_version.
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('002_maker_checker');

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lending_checker') THEN
        CREATE ROLE lending_checker NOLOGIN;
    END IF;
END $$;

CREATE FUNCTION parameter_sets_govern() RETURNS trigger LANGUAGE plpgsql AS $$
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
    ELSIF OLD.status = 'proposed' AND NEW.status IN ('approved', 'rejected') AND is_checker AND who <> OLD.maker THEN
        NEW.checker := who;
        NEW.checked_at := now();
        RETURN NEW;
    ELSIF (OLD.status, NEW.status) IN (('approved', 'active'), ('active', 'retired')) AND is_checker THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% may not move parameter set % from % to %', who, OLD.param_version, OLD.status, NEW.status
        USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER parameter_sets_govern BEFORE INSERT OR UPDATE ON parameter_sets
    FOR EACH ROW EXECUTE FUNCTION parameter_sets_govern();

-- Checkers read parameters and change status; nothing else.
GRANT USAGE ON SCHEMA public TO lending_checker;
GRANT SELECT ON parameter_sets, audit TO lending_checker;
GRANT UPDATE (status) ON parameter_sets TO lending_checker;

COMMIT;
