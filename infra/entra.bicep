// Entra ID objects for the decision API: who may call it, decided by identity and app role, not by IP.
//
// Deploy (as a user who can register applications), passing the people to assign at deploy time:
//   az deployment group create -g rg-digitallending-dev -f infra/entra.bicep \
//     -p decisionReaders='["<user object id>"]' eventWriters='["<user object id>"]' \
//        parameterApprovers='["<user object id>"]' apiIdentityPrincipalId=<API managed identity principal id>
// (PowerShell mangles inline JSON: pass these in a parameters file.)
// Outputs apiClientId and tenantId: the API validates tokens against them (set on the Container App).
//
// - App roles, not scopes, carry the permission: Decisions.Read (GET /decisions), Events.Write (POST /events),
//   Parameters.Approve (/parameter-sets; users only, since approving is a person's act).
//   They can be assigned to users (for testing from a terminal) and to apps / managed identities (callers).
// - appRoleAssignmentRequired: Entra issues tokens for this API only to principals assigned a role.
// - access_as_user is the delegated scope a user token needs; the az CLI (a Microsoft public client, well-known
//   id below) is pre-authorised for it, so `az account get-access-token --scope <apiClientId>/.default` works
//   without a consent prompt. Its token still carries only the user's assigned roles.
// - No client secrets: callers use their own sign-in or a managed identity.
// - On-behalf-of to Postgres (/parameter-sets): the app may sign users in to Azure Postgres (delegated
//   user_impersonation, admin-consented for the tenant), and authenticates itself to Entra with the API's managed
//   identity through a federated credential, so the exchange needs no secret either.
extension microsoftGraphV1

@description('Unique name of the application; also its display name.')
param appName string = 'lending-api-dev'

@description('Object ids of users or service principals given Decisions.Read.')
param decisionReaders array = []

@description('Object ids of users or service principals given Events.Write.')
param eventWriters array = []

@description('Object ids of users given Parameters.Approve (the database still requires them to be checkers).')
param parameterApprovers array = []

@description('Principal (object) id of the API\'s managed identity: the credential the app uses for on-behalf-of.')
param apiIdentityPrincipalId string

var azureCliClientId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46' // Microsoft Azure CLI, a first-party public client
var postgresAppId = '123cd850-d9df-40bd-94d5-c9f07b7fa203' // Azure OSSRDBMS Database, first-party (same in every tenant)
var scopeId = guid(appName, 'access_as_user')
var roles = {
  read: {
    id: guid(appName, 'Decisions.Read')
    value: 'Decisions.Read'
    displayName: 'Read decisions'
    description: 'Read published offer/hold decisions and their reasons.'
  }
  write: {
    id: guid(appName, 'Events.Write')
    value: 'Events.Write'
    displayName: 'Write events'
    description: 'Send partner events (disbursements, repayments, offers, responses).'
  }
  approve: {
    id: guid(appName, 'Parameters.Approve')
    value: 'Parameters.Approve'
    displayName: 'Approve parameter sets'
    description: 'Review, approve, reject and activate model parameter sets, as yourself.'
  }
}

resource postgres 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: postgresAppId
}

resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: appName
  displayName: appName
  signInAudience: 'AzureADMyOrg'
  identifierUris: ['api://${tenant().tenantId}/${appName}']
  appRoles: [
    for r in items(roles): {
      id: r.value.id
      value: r.value.value
      displayName: r.value.displayName
      description: r.value.description
      allowedMemberTypes: r.key == 'approve' ? ['User'] : ['User', 'Application']
      isEnabled: true
    }
  ]
  requiredResourceAccess: [
    {
      resourceAppId: postgresAppId
      resourceAccess: [
        { id: filter(postgres.oauth2PermissionScopes, s => s.value == 'user_impersonation')[0].id, type: 'Scope' }
      ]
    }
  ]
  api: {
    requestedAccessTokenVersion: 2 // v2 tokens: aud = this app's client id, iss = .../{tenant}/v2.0
    oauth2PermissionScopes: [
      {
        id: scopeId
        value: 'access_as_user'
        type: 'User'
        adminConsentDisplayName: 'Call the lending decision API as you'
        adminConsentDescription: 'Lets the app call the lending decision API with the signed-in user\'s roles.'
        userConsentDisplayName: 'Call the lending decision API as you'
        userConsentDescription: 'Lets the app call the lending decision API with your roles.'
        isEnabled: true
      }
    ]
    preAuthorizedApplications: [
      { appId: azureCliClientId, delegatedPermissionIds: [scopeId] }
    ]
  }
}

resource sp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: app.appId
  appRoleAssignmentRequired: true
}

// The API's managed identity is the app's credential: it presents its own token as a client assertion.
resource apiIdentity 'Microsoft.Graph/applications/federatedIdentityCredentials@v1.0' = {
  name: '${app.uniqueName}/api-managed-identity'
  issuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
  subject: apiIdentityPrincipalId
  audiences: ['api://AzureADTokenExchange']
}

// Tenant-wide admin consent for the delegated Postgres permission, so approvers get no consent prompt.
resource postgresConsent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = {
  clientId: sp.id
  consentType: 'AllPrincipals'
  resourceId: postgres.id
  scope: 'user_impersonation'
}

resource readers 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [
  for p in decisionReaders: {
    principalId: p
    resourceId: sp.id
    appRoleId: roles.read.id
  }
]

resource writers 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [
  for p in eventWriters: {
    principalId: p
    resourceId: sp.id
    appRoleId: roles.write.id
  }
]

resource approvers 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [
  for p in parameterApprovers: {
    principalId: p
    resourceId: sp.id
    appRoleId: roles.approve.id
  }
]

output apiClientId string = app.appId
output tenantId string = tenant().tenantId
