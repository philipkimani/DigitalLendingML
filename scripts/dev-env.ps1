<#
Connection settings for the dev database, as the Entra admin, for psql and the local job runs.

    . .\scripts\dev-env.ps1        # dot-source: the variables stay in your PowerShell session

Sets the standard libpq variables (PGHOST, PGUSER, PGPASSWORD, PGDATABASE, PGSSLMODE) from the az CLI sign-in.
PGUSER is the admin's Postgres role name, which for an Entra guest is the #EXT# name, not the email.
PGPASSWORD is an Entra access token: it lasts about an hour; dot-source again when psql says the password failed.
Also warns when this machine's public IP is not the one the dev-client firewall rule allows (fix with
.\scripts\allow-my-ip.ps1).
#>
param([string]$ResourceGroup = "rg-digitallending-dev")

$server = az postgres flexible-server list -g $ResourceGroup --query "[0].name" -o tsv
if (-not $server) { throw "no Postgres server in $ResourceGroup (signed in to the right subscription? az account show)" }

$env:PGHOST = az postgres flexible-server show -g $ResourceGroup -n $server --query fullyQualifiedDomainName -o tsv
$env:PGUSER = az postgres flexible-server microsoft-entra-admin list -g $ResourceGroup -s $server --query "[0].principalName" -o tsv
$env:PGPASSWORD = az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv
$env:PGDATABASE = "lending"
$env:PGSSLMODE = "require"

$ip = (Invoke-RestMethod https://api.ipify.org).Trim()
$allowed = az postgres flexible-server firewall-rule show -g $ResourceGroup -s $server -n dev-client --query startIpAddress -o tsv
Write-Host "PGHOST=$env:PGHOST PGUSER=$env:PGUSER (token set, ~1 h)"
if ($ip -ne $allowed) {
    Write-Warning "your IP is $ip but dev-client allows ${allowed}: connections will time out. Run .\scripts\allow-my-ip.ps1"
}
