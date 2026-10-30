<#
Point the Postgres dev-client firewall rule at this machine's current public IP.

    .\scripts\allow-my-ip.ps1

STOPGAP. The rule breaks whenever the ISP hands out a new address. The fix is private networking for the
database (hardening step). The decision API has no IP allow-list: callers need an Entra token instead.
#>
param([string]$ResourceGroup = "rg-digitallending-dev")
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true # a failing az call stops the script

$ip = (Invoke-RestMethod https://api.ipify.org).Trim()
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "unexpected answer for the public IP: $ip" }
$server = az postgres flexible-server list -g $ResourceGroup --query "[0].name" -o tsv
$dbIp = az postgres flexible-server firewall-rule show -g $ResourceGroup -s $server -n dev-client --query startIpAddress -o tsv
Write-Host "current IP $ip | Postgres dev-client $dbIp"

if ($dbIp -eq $ip) { Write-Host "nothing to change"; return }
az postgres flexible-server firewall-rule update -g $ResourceGroup -s $server -n dev-client `
    --start-ip-address $ip --end-ip-address $ip -o none
Write-Host "Postgres dev-client -> $ip"
