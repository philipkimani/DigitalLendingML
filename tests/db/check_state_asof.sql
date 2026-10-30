-- Checks for customer_state_asof (migration 003): hand-built events with known answers. Runs as the Entra
-- admin in `lending` and rolls back, so it leaves no data behind:
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f tests/db/check_state_asof.sql
-- As of 2026-06-30 00:00 UTC. Customer ids 900001+ are reserved for these checks.

BEGIN;
SET LOCAL TimeZone = 'Africa/Nairobi'; -- UTC+3: year boundaries must still be UTC

CREATE FUNCTION pg_temp.ev(id text, cust bigint, typ text, at timestamptz, p jsonb, received timestamptz DEFAULT NULL)
RETURNS void LANGUAGE sql AS $$
    INSERT INTO events (event_id, customer_id, event_type, occurred_at, received_at, payload)
    VALUES ('check-' || id, cust, typ, at, coalesce(received, at), p)
$$;

-- 900001: the full set of rules.
SELECT pg_temp.ev('a1', 900001, 'disburse', '2025-11-01Z', '{"loan_id": "L0", "amount": 800}');
SELECT pg_temp.ev('a2', 900001, 'disburse', '2026-02-01Z', '{"loan_id": "L1", "amount": 1000}');  -- L0: first this year
SELECT pg_temp.ev('a3', 900001, 'disburse', '2026-05-01Z', '{"loan_id": "L2", "amount": 1150}');  -- latest: 60 days
SELECT pg_temp.ev('a4', 900001, 'disburse', '2026-07-01Z', '{"loan_id": "L3", "amount": 1300}');  -- after T: ignored
-- instalments: 4 in the window, 3 on time -> 75.00
SELECT pg_temp.ev('b1', 900001, 'repay', '2026-02-28Z', '{"loan_id": "L1", "amount": 500, "due_at": "2026-03-01T00:00:00+00:00"}');
SELECT pg_temp.ev('b2', 900001, 'miss',  '2026-04-02Z', '{"loan_id": "L1", "due_at": "2026-04-01T00:00:00+00:00"}');
SELECT pg_temp.ev('b3', 900001, 'repay', '2026-04-10Z', '{"loan_id": "L1", "amount": 500, "due_at": "2026-04-01T00:00:00+00:00"}'); -- late: same instalment
SELECT pg_temp.ev('b4', 900001, 'repay', '2026-05-15Z', '{"loan_id": "L2", "amount": 600, "due_at": "2026-05-15T00:00:00+00:00"}'); -- exactly on the due time
SELECT pg_temp.ev('b5', 900001, 'repay', '2026-05-20Z', '{"loan_id": "L2", "amount": 300, "due_at": "2026-06-01T00:00:00+00:00"}'); -- two partial payments,
SELECT pg_temp.ev('b6', 900001, 'repay', '2026-05-25Z', '{"loan_id": "L2", "amount": 300, "due_at": "2026-06-01T00:00:00+00:00"}'); -- one instalment
SELECT pg_temp.ev('b7', 900001, 'repay', '2026-06-01Z', '{"loan_id": "L2", "amount": 300, "due_at": "2026-07-15T00:00:00+00:00"}'); -- not yet due: ignored
SELECT pg_temp.ev('b8', 900001, 'miss',  '2025-06-02Z', '{"loan_id": "L0", "due_at": "2025-06-01T00:00:00+00:00"}'); -- older than 365 days: ignored
SELECT pg_temp.ev('b9', 900001, 'repay', '2026-06-19Z', '{"loan_id": "L2", "amount": 300, "due_at": "2026-06-20T00:00:00+00:00"}',
                  '2026-07-02Z');                                                                     -- arrived after T: ignored
-- accepts: offers A, B (twice), D in 2025 UTC -> 3; C is this year, Z two years ago
SELECT pg_temp.ev('c1', 900001, 'accept', '2025-03-01Z', '{"offer_id": "A"}');
SELECT pg_temp.ev('c2', 900001, 'accept', '2025-08-01Z', '{"offer_id": "B"}');
SELECT pg_temp.ev('c3', 900001, 'accept', '2025-08-02Z', '{"offer_id": "B"}');                  -- same offer again
SELECT pg_temp.ev('c4', 900001, 'accept', '2025-12-31T22:00Z', '{"offer_id": "D"}');            -- 2026 in Nairobi, 2025 in UTC
SELECT pg_temp.ev('c5', 900001, 'accept', '2026-01-15Z', '{"offer_id": "C"}');
SELECT pg_temp.ev('c6', 900001, 'accept', '2024-12-01Z', '{"offer_id": "Z"}');

-- 900002: no disbursement this year (L0 = latest), all missed, increases capped at 6.
SELECT pg_temp.ev('d1', 900002, 'disburse', '2025-12-20Z', '{"loan_id": "M1", "amount": 600}');
SELECT pg_temp.ev('d2', 900002, 'miss', '2026-01-21Z', '{"loan_id": "M1", "due_at": "2026-01-20T00:00:00+00:00"}');
SELECT pg_temp.ev('e' || i, 900002, 'accept', make_timestamptz(2025, i, 1, 0, 0, 0, 'UTC'), jsonb_build_object('offer_id', 'O' || i))
FROM generate_series(1, 7) i;

-- 900003: disbursed, nothing due yet -> left out.  900004: an instalment but no disbursement -> left out.
SELECT pg_temp.ev('f1', 900003, 'disburse', '2026-06-01Z', '{"loan_id": "N1", "amount": 900}');
SELECT pg_temp.ev('f2', 900004, 'repay', '2026-03-01Z', '{"loan_id": "P1", "amount": 100, "due_at": "2026-03-01T00:00:00+00:00"}');

DO $$
DECLARE
    got text := (SELECT string_agg(format('%s,%s,%s,%s,%s', customer_id, loan_amount, days_since_last_loan,
                                          ontime_pct, n_increases), ' | ' ORDER BY customer_id)
                 FROM customer_state_asof('2026-06-30T00:00:00Z') WHERE customer_id >= 900001);
    want text := '900001,1000.00,60,75.00,3 | 900002,600.00,192,0.00,6';
BEGIN
    IF got IS DISTINCT FROM want THEN
        RAISE EXCEPTION E'FAIL: customer_state_asof\n  got:  %\n  want: %', got, want;
    END IF;
    RAISE NOTICE 'ok: derived state matches (L0, days, on-time share, increases, exclusions, as-of cut-offs)';
END $$;

-- Same T, same answer, whatever arrives later (the reproducibility promise).
SELECT pg_temp.ev('g1', 900002, 'repay', '2026-06-29Z', '{"loan_id": "M1", "amount": 50, "due_at": "2026-06-29T00:00:00+00:00"}',
                  now());
DO $$ BEGIN
    IF (SELECT ontime_pct FROM customer_state_asof('2026-06-30T00:00:00Z') WHERE customer_id = 900002) <> 0 THEN
        RAISE EXCEPTION 'FAIL: an event received after T changed the state as of T';
    END IF;
    RAISE NOTICE 'ok: late arrival does not change a past as-of';
END $$;

DO $$ BEGIN
    IF NOT has_function_privilege('lending_app', 'customer_state_asof(timestamptz)', 'EXECUTE')
       OR has_function_privilege('public', 'customer_state_asof(timestamptz)', 'EXECUTE') THEN
        RAISE EXCEPTION 'FAIL: EXECUTE should be lending_app only';
    END IF;
    RAISE NOTICE 'ok: only lending_app may call customer_state_asof';
END $$;

ROLLBACK;
