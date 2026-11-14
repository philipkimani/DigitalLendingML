-- 008_reporting_reader: a read-only role for Power BI (roadmap 2.6).
--
-- Power BI reads the database directly, signed in as a person with their Entra account (the "Azure Database for
-- PostgreSQL" connector, Organizational account; refresh is manual in this PoC). The person is granted this role,
-- which can only SELECT the tables a portfolio report needs. No writes, no events, no audit. 009 adds its tables.
--   GRANT lending_reporting TO "<person's Entra login>";   -- per person, at run time, never committed
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('008_reporting_reader');

DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lending_reporting') THEN
        CREATE ROLE lending_reporting NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO lending_reporting;
GRANT SELECT ON runs, decisions, parameter_sets, customer_state, run_scenarios TO lending_reporting;

COMMIT;
