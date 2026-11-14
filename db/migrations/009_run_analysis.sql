-- 009_run_analysis: the report's tables for the published run, written by jobs/analysis.py, read by Power BI.
--
--   run_strategies   strategy comparison per macro scenario (report summary table and Q4): NPV mean and P5-P95,
--                    increases, default rate, churn, capital; lambda for solved policies, NULL for rules
--   run_forecast     expected increases per calendar month for each of those (report Q4 uptake forecast)
--   run_sensitivity  one assumption changed at a time, re-solved at its own capital price (report section 5)
--
-- Kept apart from run_scenarios on purpose: those are business levers the internal agent offers; these are
-- assumptions and benchmarks for analysts. Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('009_run_analysis');

CREATE TABLE run_strategies (
    run_id       bigint NOT NULL REFERENCES runs,
    scenario     text NOT NULL CHECK (scenario IN ('base', 'adverse', 'benign')),
    strategy     text NOT NULL
                 CHECK (strategy IN ('historical', 'grant_all', 'scorecard', 'optimal_free', 'optimal', 'base_policy')),
    lambda       double precision CHECK (lambda >= 0),
    npv_mean     double precision NOT NULL,
    npv_p5       double precision NOT NULL,
    npv_p95      double precision NOT NULL,
    increases    double precision NOT NULL CHECK (increases >= 0),
    default_rate double precision NOT NULL CHECK (default_rate BETWEEN 0 AND 1),
    churn_rate   double precision NOT NULL CHECK (churn_rate BETWEEN 0 AND 1),
    capital      double precision NOT NULL CHECK (capital >= 0),
    PRIMARY KEY (run_id, scenario, strategy),
    CHECK (npv_p5 <= npv_mean AND npv_mean <= npv_p95)
);

CREATE TABLE run_forecast (
    run_id    bigint NOT NULL,
    scenario  text NOT NULL,
    strategy  text NOT NULL,
    month     smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    increases double precision NOT NULL CHECK (increases >= 0),
    PRIMARY KEY (run_id, scenario, strategy, month),
    FOREIGN KEY (run_id, scenario, strategy) REFERENCES run_strategies ON DELETE CASCADE
);

CREATE TABLE run_sensitivity (
    run_id       bigint NOT NULL REFERENCES runs,
    param        text NOT NULL CHECK (param IN ('lgd', 'c_deny', 'kappa', 'step', 'gamma', 'fixed_cost')),
    value        double precision NOT NULL,
    lambda       double precision NOT NULL CHECK (lambda >= 0),
    offers       integer NOT NULL CHECK (offers >= 0),
    capital_used double precision NOT NULL CHECK (capital_used >= 0),
    npv          double precision NOT NULL,
    default_rate double precision NOT NULL CHECK (default_rate BETWEEN 0 AND 1),
    PRIMARY KEY (run_id, param, value)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON run_strategies, run_forecast, run_sensitivity TO lending_app;
GRANT SELECT ON run_strategies, run_forecast, run_sensitivity TO lending_reporting;

COMMIT;
