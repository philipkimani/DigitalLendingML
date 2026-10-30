<#
Point both dev allow-lists at this machine's current public IP: the Postgres dev-client firewall rule and the
decision API's ingress allow-list.

    .\scripts\allow-my-ip.ps1          # shows the current state and the Bicep what-if, asks before deploying
    .\scripts\allow-my-ip.ps1 -Yes     # no question (still stops on anything unexpected)

STOPGAP. IP allow-lists break whenever the ISP hands out a new address. The fixes are Entra auth on the API
(callers are checked by identity, not address) and private networking for the database (hardening step).

The API side goes through infra/main.bicep, not a direct az call, so the template and Azure never disagree.
The deploy passes the image that is running now, and refuses while the api workflow is still rolling one out
(deploying then would set the old image back).
#>
param([string]$ResourceGroup = "rg-digitallending-dev", [switch]$Yes)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true # a failing az/gh call stops the script

$ip = (Invoke-RestMethod https://api.ipify.org).Trim()
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "unexpected answer for the public IP: $ip" }
$server = az postgres flexible-server list -g $ResourceGroup --query "[0].name" -o tsv
$app = az containerapp list -g $ResourceGroup --query "[0].name" -o tsv
$dbIp = az postgres flexible-server firewall-rule show -g $ResourceGroup -s $server -n dev-client --query startIpAddress -o tsv
$apiIp = (az containerapp show -g $ResourceGroup -n $app `
        --query "properties.configuration.ingress.ipSecurityRestrictions[0].ipAddressRange" -o tsv) -replace '/32$', ''
Write-Host "current IP $ip | Postgres dev-client $dbIp | API allow-list $apiIp"

if ($dbIp -ne $ip) {
    az postgres flexible-server firewall-rule update -g $ResourceGroup -s $server -n dev-client `
        --start-ip-address $ip --end-ip-address $ip -o none
    Write-Host "Postgres dev-client -> $ip"
}

if ($apiIp -eq $ip) { Write-Host "API allow-list already $ip"; return }

$ci = gh run list --workflow api.yml -L 1 --json status --jq '.[0].status'
if ($ci -ne "completed") { throw "the api workflow is still ${ci}: wait until it finishes, then run this again" }

$image = az containerapp show -g $ResourceGroup -n $app --query "properties.template.containers[0].image" -o tsv
$repo = gh api 'repos/{owner}/{repo}' | ConvertFrom-Json
$githubRepo = "$($repo.owner.login)@$($repo.owner.id)/$($repo.name)@$($repo.id)" # GitHub's immutable-id OIDC subject
if ($githubRepo -notmatch '^[^@/]+@\d+/[^@/]+@\d+$') { throw "unexpected githubRepo: $githubRepo" }
$params = @(
    "adminObjectId=$(az ad signed-in-user show --query id -o tsv)",
    "adminName=$(az postgres flexible-server microsoft-entra-admin list -g $ResourceGroup -s $server --query '[0].principalName' -o tsv)",
    "apiImage=$image", "allowedIp=$ip", "githubRepo=$githubRepo",
    "apiAudience=$(az ad app list --display-name lending-api-dev --query '[0].appId' -o tsv)"
)

# What-if, real changes only: lines with "=>" minus the reference() values what-if can't resolve (known noise).
$changes = az deployment group what-if -g $ResourceGroup -f infra/main.bicep -p @params 2>&1 |
    Select-String '=>' | Where-Object { $_.Line -notmatch '\[reference\(' } | ForEach-Object { $_.Line.Trim() }
Write-Host "what-if:`n  $($changes -join "`n  ")"
$expected = '^~ (ipAddressRange|properties\.properties\.remoteLoginPortPublicAccess):' # the allow-list + known noise
if ($changes | Where-Object { $_ -notmatch $expected }) { throw "what-if shows more than the allow-list change: review it by hand" }

if (-not $Yes -and (Read-Host "deploy? (y/N)") -ne "y") { Write-Host "not deployed"; return }
$state = az deployment group create -g $ResourceGroup -n "allowedip-$(Get-Date -Format yyyyMMddHHmm)" `
    -f infra/main.bicep -p @params --query properties.provisioningState -o tsv
Write-Host "Bicep deploy: $state; API allow-list -> $ip (image unchanged: $($image -replace '.*:', ''))"
