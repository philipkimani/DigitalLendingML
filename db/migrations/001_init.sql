-- 001_init: operational schema for the lending database.
--
-- Run as the Entra admin against the `lending` database:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f db/migrations/001_init.sql
-- One transaction: it applies completely or not at all. Re-running fails on the version row.
--
-- Rules enforced here rather than only in code (the database is the last line of defence):
--   * parameter bounds and maker-checker on parameter_sets,
--   * at most one active parameter set and one published run,
--   * every decision carries the param_version and model_version of the run that made it,
--   * least privilege: the application role can read inputs, write runs/decisions/events, nothing else.

BEGIN;

CREATE TABLE schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text NOT NULL DEFAULT current_user
);
INSERT INTO schema_migrations (version) VALUES ('001_init');

-- --- events: raw partner events, append-only -----------------------------------------------------
-- The partner's event_id is the primary key, so a retried delivery is a no-op
-- (INSERT ... ON CONFLICT (event_id) DO NOTHING) instead of a duplicate.
-- No foreign key to customer_state: state is rebuilt from events, so an event may arrive first.
-- ponytail: unpartitioned; at ~5M events/week partition by month on occurred_at, which needs
-- occurred_at in the key, so idempotency then moves to a separate event_id lookup table.
CREATE TABLE events (
    event_id    text PRIMARY KEY CHECK (length(event_id) BETWEEN 1 AND 128),
    customer_id bigint NOT NULL CHECK (customer_id >= 0),
    event_type  text NOT NULL CHECK (event_type IN ('disburse', 'repay', 'miss', 'offer', 'accept', 'decline')),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    payload     jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX events_customer_time ON events (customer_id, occurred_at);

-- --- customer_state: the model input, one row per customer ---------------------------------------
-- Same columns and ranges as the data contract (src/lending/contract.py, docs/data_card.md).
CREATE TABLE customer_state (
    customer_id          bigint PRIMARY KEY CHECK (customer_id >= 0),
    loan_amount          numeric(10, 2) NOT NULL CHECK (loan_amount BETWEEN 500 AND 5000),
    days_since_last_loan integer NOT NULL CHECK (days_since_last_loan BETWEEN 0 AND 364),
    ontime_pct           numeric(5, 2) NOT NULL CHECK (ontime_pct BETWEEN 0 AND 100),
    n_increases          integer NOT NULL CHECK (n_increases BETWEEN 0 AND 6),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

-- --- parameter_sets: versioned model assumptions, maker-checker ---------------------------------
-- One column per field of lending.params.Params, so a row rebuilds the exact Params object.
-- Bounds are wide enough for sensitivity runs and narrow enough to reject typos (e.g. lgd = 65).
CREATE TABLE parameter_sets (
    param_version integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status        text NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft', 'proposed', 'approved', 'active', 'retired', 'rejected')),
    note          text NOT NULL,
    maker         text NOT NULL DEFAULT current_user,
    created_at    timestamptz NOT NULL DEFAULT now(),
    checker       text,
    checked_at    timestamptz,

    n0         double precision NOT NULL CHECK (n0 > 0 AND n0 <= 1000),
    kappa      double precision NOT NULL CHECK (kappa > 0 AND kappa <= 1),
    early      double precision NOT NULL CHECK (early BETWEEN 0 AND 1),
    early_fee  double precision NOT NULL CHECK (early_fee BETWEEN 0 AND 1),
    gamma      double precision NOT NULL CHECK (gamma BETWEEN 0 AND 1),
    step       double precision NOT NULL CHECK (step > 0 AND step <= 1),
    lgd        double precision NOT NULL CHECK (lgd BETWEEN 0 AND 1),
    m          double precision NOT NULL CHECK (m BETWEEN 0 AND 0.5),
    fee        double precision NOT NULL CHECK (fee BETWEEN 0 AND 1000),
    c0         double precision NOT NULL CHECK (c0 BETWEEN 0 AND 0.5),
    c_deny     double precision NOT NULL CHECK (c_deny BETWEEN 0 AND 0.5),
    k_prime    double precision NOT NULL CHECK (k_prime > 0 AND k_prime <= 1),
    k_near     double precision NOT NULL CHECK (k_near > 0 AND k_near <= 1),
    k_sub      double precision NOT NULL CHECK (k_sub > 0 AND k_sub <= 1),
    budget     double precision NOT NULL CHECK (budget > 0),
    disc       double precision NOT NULL CHECK (disc BETWEEN 0 AND 1),
    fixed_cost double precision NOT NULL CHECK (fixed_cost >= 0),
    fatigue    double precision NOT NULL CHECK (fatigue BETWEEN 0 AND 5),
    horizon    integer NOT NULL CHECK (horizon BETWEEN 1 AND 366),
    cycle      integer NOT NULL CHECK (cycle BETWEEN 1 AND 366),
    max_k      integer NOT NULL CHECK (max_k BETWEEN 0 AND 12),

    -- Maker-checker: anything past review names a checker who is not the maker.
    CONSTRAINT checked_by_someone_else CHECK (
        status IN ('draft', 'proposed')
        OR (checker IS NOT NULL AND checked_at IS NOT NULL AND checker <> maker)
    )
);
-- At most one active parameter set.
CREATE UNIQUE INDEX parameter_sets_one_active ON parameter_sets ((true)) WHERE status = 'active';

-- --- runs: one nightly solve -----------------------------------------------------------------------
-- Publishing is a status flip in one transaction (old run -> superseded, new run -> published),
-- so the API always serves one complete run, never a half-written one.
CREATE TABLE runs (
    run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status        text NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'failed', 'published', 'superseded')),
    param_version integer NOT NULL REFERENCES parameter_sets,
    model_version text NOT NULL CHECK (model_version ~ '^[0-9a-f]{7,40}$'), -- git SHA
    data_version  text NOT NULL,                                           -- e.g. azureml:customer-book:1
    lambda        double precision CHECK (lambda >= 0),                    -- shadow price of capital
    started_at    timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    CONSTRAINT published_has_time CHECK (status NOT IN ('published', 'superseded') OR published_at IS NOT NULL),
    UNIQUE (run_id, param_version, model_version) -- target of the decisions foreign key below
);
CREATE UNIQUE INDEX runs_one_published ON runs ((true)) WHERE status = 'published';

-- --- decisions: offer or hold, per customer per run ------------------------------------------------
-- param_version and model_version are on every row (each decision is self-describing), and the
-- composite foreign key guarantees they match the run that produced it.
CREATE TABLE decisions (
    run_id        bigint NOT NULL,
    customer_id   bigint NOT NULL CHECK (customer_id >= 0),
    param_version integer NOT NULL,
    model_version text NOT NULL,
    action        text NOT NULL CHECK (action IN ('offer', 'hold')),
    q_offer       double precision,
    q_hold        double precision,
    reason_code   text,
    PRIMARY KEY (run_id, customer_id), -- also serves the API lookup: published run + customer
    FOREIGN KEY (run_id, param_version, model_version) REFERENCES runs (run_id, param_version, model_version)
);

-- --- audit: who changed what, written by trigger -----------------------------------------------------
-- Covers the governed tables (parameter_sets, runs). Not decisions or events: those are bulk
-- data whose provenance is already in the row itself.
CREATE TABLE audit (
    audit_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL DEFAULT session_user,
    table_name text NOT NULL,
    op         text NOT NULL CHECK (op IN ('INSERT', 'UPDATE', 'DELETE')),
    old_row    jsonb,
    new_row    jsonb
);

-- SECURITY DEFINER: the trigger writes audit with the owner's rights, so the application role
-- needs no privilege on audit at all and cannot edit its own trail. session_user (above) still
-- records the real caller, not the function owner.
CREATE FUNCTION audit_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    INSERT INTO audit (table_name, op, old_row, new_row)
    VALUES (TG_TABLE_NAME, TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION audit_row() FROM PUBLIC;

CREATE TRIGGER parameter_sets_audit AFTER INSERT OR UPDATE OR DELETE ON parameter_sets
    FOR EACH ROW EXECUTE FUNCTION audit_row();
CREATE TRIGGER runs_audit AFTER INSERT OR UPDATE OR DELETE ON runs
    FOR EACH ROW EXECUTE FUNCTION audit_row();

-- --- least-privilege application role ----------------------------------------------------------------
-- lending_app is a group role (NOLOGIN) that holds the grants; the managed identity is made a member
-- of it (db/bootstrap_identity.sql). Swapping identities never touches grants.
-- No UPDATE/DELETE on events (append-only), no write on customer_state or parameter_sets
-- (parameter changes go through maker-checker, Phase 2 gives that its own role), nothing on audit.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lending_app') THEN
        CREATE ROLE lending_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO lending_app;
GRANT SELECT ON customer_state, parameter_sets, schema_migrations TO lending_app;
GRANT SELECT, INSERT ON events TO lending_app;
GRANT SELECT, INSERT, UPDATE ON runs TO lending_app;
GRANT SELECT, INSERT ON decisions TO lending_app;

COMMIT;
