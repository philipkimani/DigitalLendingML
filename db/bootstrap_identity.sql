-- Map an Entra principal to a Postgres login and make it a member of one group role.
--
-- Run once per principal and environment, after the migrations, as the Entra admin against the
-- `postgres` database (pgaadauth_create_principal only works there; roles are server-wide):
--   psql "host=<server>.postgres.database.azure.com dbname=postgres user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -v identity=<name> -v role=<group role> [-v oid=<object id>] -f db/bootstrap_identity.sql
-- identity: a managed identity's display name or a user's UPN; Postgres resolves it in Entra.
-- role:     lending_app (the API / nightly job identity) or lending_checker (a human approver).
-- oid:      for a person who approves through the API: their Entra object id. The API finds a caller's
--           database login by this id (api/main.py, LOGIN_ROLE_SQL), since a token's names don't reliably
--           match role names (guests). Re-running with only -v oid set labels an existing role.

\if :{?role}
SELECT * FROM pgaadauth_create_principal(:'identity', false, false); -- not admin, not MFA-required
GRANT :"role" TO :"identity";
\endif
\if :{?oid}
\set label 'aadauth,oid=' :oid ',type=user'
SECURITY LABEL FOR "pgaadauth" ON ROLE :"identity" IS :'label';
\endif
