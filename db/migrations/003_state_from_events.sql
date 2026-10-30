-- 003_state_from_events: the model's four inputs per customer, derived from the event log as of a moment.
--
-- customer_state_asof(T) uses only events that had both happened (occurred_at <= T) and reached us
-- (received_at <= T) by T. Events are append-only, so the same T always gives the same rows: a run that records
-- its T (runs.state_as_of) can be rebuilt exactly, even after late events arrive. No snapshot table, and the
-- app role needs no write access to state: it already reads events.
--
-- Derivation (payload fields are enforced at ingest, api/main.py):
--   ontime_pct            instalments due in the 365 days up to T, one per (loan_id, due_at): the share with a
--                         repay at or before due_at. A late repay after a miss still counts once, as late.
--   loan_amount           L0: the first disbursement this calendar year (UTC), else the latest one before.
--   days_since_last_loan  days from the latest disbursement to T, capped at 364.
--   n_increases           distinct offers accepted in the previous calendar year (UTC), capped at 6.
-- Customers with no disbursement or no instalment due in the window are left out (the caller reports how many).
-- Range checks (e.g. loan_amount 500-5000) stay with the data contract in the job, not here.
--
-- ponytail: scans a year of events per call; fine at dev volume. At ~5M events/week, keep a daily per-customer
-- rollup table updated incrementally and derive from that.
--
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('003_state_from_events');

ALTER TABLE runs ADD COLUMN state_as_of timestamptz; -- NULL: the run read the customer_state table (dev seed)

CREATE FUNCTION customer_state_asof(as_of timestamptz)
RETURNS TABLE (
    customer_id          bigint,
    loan_amount          numeric(10, 2),
    days_since_last_loan integer,
    ontime_pct           numeric(5, 2),
    n_increases          integer
)
LANGUAGE sql STABLE
AS $$
    WITH ev AS (
        SELECT * FROM events WHERE occurred_at <= as_of AND received_at <= as_of
    ),
    yr AS (
        SELECT date_trunc('year', as_of, 'UTC') AS start -- calendar year in UTC, whatever the session time zone
    ),
    disb AS (
        SELECT e.customer_id,
               (array_agg((e.payload ->> 'amount')::numeric ORDER BY e.occurred_at, e.event_id)
                    FILTER (WHERE e.occurred_at >= yr.start))[1]                                 AS first_this_year,
               (array_agg((e.payload ->> 'amount')::numeric ORDER BY e.occurred_at DESC, e.event_id DESC))[1] AS latest,
               max(e.occurred_at)                                                                AS last_at
        FROM ev e, yr
        WHERE e.event_type = 'disburse'
        GROUP BY e.customer_id
    ),
    instalment AS ( -- one row per instalment due in the window
        SELECT customer_id,
               bool_or(event_type = 'repay' AND occurred_at <= (payload ->> 'due_at')::timestamptz) AS on_time
        FROM ev
        WHERE event_type IN ('repay', 'miss')
          AND (payload ->> 'due_at')::timestamptz > as_of - interval '365 days'
          AND (payload ->> 'due_at')::timestamptz <= as_of
        GROUP BY customer_id, payload ->> 'loan_id', (payload ->> 'due_at')::timestamptz
    ),
    reliability AS (
        SELECT customer_id, round(100.0 * count(*) FILTER (WHERE on_time) / count(*), 2) AS ontime_pct
        FROM instalment
        GROUP BY customer_id
    ),
    increases AS (
        SELECT e.customer_id, count(DISTINCT e.payload ->> 'offer_id') AS n
        FROM ev e, yr
        WHERE e.event_type = 'accept' AND e.occurred_at >= yr.start - interval '1 year' AND e.occurred_at < yr.start
        GROUP BY e.customer_id
    )
    SELECT d.customer_id,
           round(coalesce(d.first_this_year, d.latest), 2),
           least(364, floor(extract(epoch FROM as_of - d.last_at) / 86400))::integer,
           r.ontime_pct,
           least(6, coalesce(i.n, 0))::integer
    FROM disb d
    JOIN reliability r USING (customer_id)
    LEFT JOIN increases i USING (customer_id)
$$;

REVOKE EXECUTE ON FUNCTION customer_state_asof(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION customer_state_asof(timestamptz) TO lending_app;

COMMIT;
