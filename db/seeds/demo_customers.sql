-- One current loan for one seed customer per reason code, so the customer agent has something to say: synthetic
-- events end on 1 January 2026, so nobody else has a loan today. The risk_return customer is overdue on purpose.
-- Idempotent on the demo- event ids. Run as the Entra admin in `lending` after a run is published. Prints the ids.
--   psql "host=<server>.postgres.database.azure.com dbname=lending user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -f db/seeds/demo_customers.sql
-- Delete with: DELETE FROM events WHERE event_id LIKE 'demo-%';

WITH picks AS (
    SELECT DISTINCT ON (d.reason_code) d.customer_id, d.reason_code, s.loan_amount
    FROM decisions d
    JOIN runs r ON r.run_id = d.run_id AND r.status = 'published'
    JOIN customer_state s USING (customer_id)
    ORDER BY d.reason_code, d.customer_id
), timing (reason_code, age_days) AS (
    VALUES ('npv_positive', 30), ('capital_limit', 53), ('risk_return', 63)
), inserted AS (
    INSERT INTO events (event_id, customer_id, event_type, occurred_at, payload)
    SELECT 'demo-' || p.reason_code, p.customer_id, 'disburse', now() - t.age_days * interval '1 day',
           jsonb_build_object('loan_id', 'demo-' || p.reason_code, 'amount', p.loan_amount,
                              'due_at', now() + (60 - t.age_days) * interval '1 day')
    FROM picks p JOIN timing t USING (reason_code)
    ON CONFLICT (event_id) DO NOTHING
)
SELECT reason_code, customer_id FROM picks ORDER BY reason_code;
