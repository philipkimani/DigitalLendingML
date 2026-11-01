-- 006_app_proposes: the estimation job (managed identity, via lending_app) may propose parameter sets.
--
-- Before: lending_app could only read parameter_sets. The monthly estimation job (jobs/estimate.py) writes its
-- estimates as a new *proposed* set. INSERT is all it needs, because the 002 trigger already
--   * refuses any new set that is not draft or proposed,
--   * records the maker from the login (the identity), whatever the client sends,
--   * refuses approval or activation by anyone who is not a checker, and by the maker.
-- lending_app gets no UPDATE, so it cannot move a set's status at all. The identity column needs no sequence
-- grant (identity sequences are used by the table's own INSERT privilege).
-- Note: the API connects with the same identity, so it gains the same INSERT; it has no endpoint that uses it.
-- Run like 001 (Entra admin, `lending` database, -v ON_ERROR_STOP=1).

BEGIN;

INSERT INTO schema_migrations (version) VALUES ('006_app_proposes');

GRANT INSERT ON parameter_sets TO lending_app;

COMMIT;
