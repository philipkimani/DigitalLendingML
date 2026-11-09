-- 007_lending_agents: what the Copilot Studio agents need.
--   * runs.capital_used: the nightly job's measured capital, until now only in MLflow. NULL on older runs.
--   * run_scenarios: precomputed what-if results per published run (jobs/scenarios.py). The API never solves.
--   * lending_maker: a person who may propose parameter sets through the API, connected as themselves. INSERT and
--     SELECT only: no UPDATE, so they can't move a set's status, and the 002 trigger records them as the maker.
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('007_lending_agents');

ALTER TABLE runs ADD COLUMN capital_used double precision CHECK (capital_used >= 0);

CREATE TABLE run_scenarios (
    run_id       bigint NOT NULL REFERENCES runs,
    lever        text NOT NULL CHECK (lever IN ('baseline', 'budget', 'step', 'fee')),
    value        double precision NOT NULL,
    lambda       double precision NOT NULL CHECK (lambda >= 0),
    offers       integer NOT NULL CHECK (offers >= 0),
    capital_used double precision NOT NULL CHECK (capital_used >= 0),
    npv          double precision NOT NULL,
    default_rate double precision NOT NULL CHECK (default_rate BETWEEN 0 AND 1),
    PRIMARY KEY (run_id, lever, value)
);
GRANT SELECT, INSERT, UPDATE ON run_scenarios TO lending_app;

DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lending_maker') THEN
        CREATE ROLE lending_maker NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO lending_maker;
GRANT SELECT, INSERT ON parameter_sets TO lending_maker;

COMMIT;
