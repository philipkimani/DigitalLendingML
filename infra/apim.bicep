// API Management (Consumption tier) in front of the lending API. Roadmap 2.5.
//
//   az deployment group create -g rg-digitallending-dev -f infra/apim.bicep \
//     -p apiAudience=<lending-api client id> publisherEmail=<email> backendUrl=<Container App https URL>
//
// Separate from main.bicep so the main deploy's parameters don't change. Consumption: no fixed cost, billed per
// call above a monthly free allowance. Callers use the gateway URL (output gatewayUrl) instead of the Container
// App URL.
//
// Limits of this tier, accepted for the PoC:
// - The Container App URL stays reachable directly (still Entra-protected). Closing it needs a tier with a fixed
//   outbound IP or virtual network, plus an allow-list on the Container App.
// - No rate-limit-by-key in Consumption; rate limits per caller need a subscription key or a higher tier.

param location string = resourceGroup().location
param env string = 'dev'
@description('Client id of the lending-api app registration (the token audience).')
param apiAudience string
@description('Email for APIM system notifications. Passed at deploy time; never committed.')
param publisherEmail string
param publisherName string = 'DigitalLendingML'
@description('Container App URL, e.g. https://ca-...azurecontainerapps.io (main.bicep output apiUrl).')
param backendUrl string

var name = 'digitallending-${env}'
var suffix = take(uniqueString(resourceGroup().id), 6)

resource apim 'Microsoft.ApiManagement/service@2023-09-01-preview' = {
  name: 'apim-${name}-${suffix}' // the name is a global DNS label, so it needs the suffix
  location: location
  sku: { name: 'Consumption', capacity: 0 }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource lendingApi 'Microsoft.ApiManagement/service/apis@2023-09-01-preview' = {
  parent: apim
  name: 'lending'
  properties: {
    displayName: 'Lending API'
    path: '' // served at the gateway root, so connectors only change their host
    protocols: [ 'https' ]
    serviceUrl: backendUrl
    subscriptionRequired: false // callers authenticate with Entra tokens, checked in the policy
  }
}

// ponytail: one wildcard operation per method instead of importing the OpenAPI spec; import it when per-operation
// policies or a developer portal are needed.
var methods = [ 'GET', 'POST', 'PUT', 'PATCH', 'DELETE' ]

resource ops 'Microsoft.ApiManagement/service/apis/operations@2023-09-01-preview' = [for m in methods: {
  parent: lendingApi
  name: 'all-${toLower(m)}'
  properties: {
    displayName: '${m} /*'
    method: m
    urlTemplate: '/*'
  }
}]

resource policy 'Microsoft.ApiManagement/service/apis/policies@2023-09-01-preview' = {
  parent: lendingApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(replace(loadTextContent('apim-policy.xml'), '__TENANT__', tenant().tenantId), '__AUDIENCE__', apiAudience)
  }
}

output gatewayUrl string = apim.properties.gatewayUrl
output apimName string = apim.name
