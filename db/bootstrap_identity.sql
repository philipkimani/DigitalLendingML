-- Map an Entra principal to a Postgres login and make it a member of one group role.
--
-- Run once per principal and environment, after the migrations, as the Entra admin against the
-- `postgres` database (pgaadauth_create_principal only works there; roles are server-wide):
--   psql "host=<server>.postgres.database.azure.com dbname=postgres user=<admin upn> sslmode=require" \
--        -v ON_ERROR_STOP=1 -v identity=<name> -v role=<group role> -f db/bootstrap_identity.sql
-- identity: a managed identity's display name or a user's UPN; Postgres resolves it in Entra.
-- role:     lending_app (the API / nightly job identity) or lending_checker (a human approver).

SELECT * FROM pgaadauth_create_principal(:'identity', false, false); -- not admin, not MFA-required
GRANT :"role" TO :"identity";
