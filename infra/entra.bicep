// Entra ID objects for the decision API: who may call it, decided by identity and app role, not by IP.
//
// Deploy (as a user who can register applications), passing the people to assign at deploy time:
//   az deployment group create -g rg-digitallending-dev -f infra/entra.bicep \
//     -p decisionReaders='["<user object id>"]' eventWriters='["<user object id>"]'
// Outputs apiClientId and tenantId: the API validates tokens against them (set on the Container App).
//
// - App roles, not scopes, carry the permission: Decisions.Read (GET /decisions), Events.Write (POST /events).
//   They can be assigned to users (for testing from a terminal) and to apps / managed identities (callers).
// - appRoleAssignmentRequired: Entra issues tokens for this API only to principals assigned a role.
// - access_as_user is the delegated scope a user token needs; the az CLI (a Microsoft public client, well-known
//   id below) is pre-authorised for it, so `az account get-access-token --scope <apiClientId>/.default` works
//   without a consent prompt. Its token still carries only the user's assigned roles.
// - No client secrets: callers use their own sign-in or a managed identity.
extension microsoftGraphV1

@description('Unique name of the application; also its display name.')
param appName string = 'lending-api-dev'

@description('Object ids of users or service principals given Decisions.Read.')
param decisionReaders array = []

@description('Object ids of users or service principals given Events.Write.')
param eventWriters array = []

var azureCliClientId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46' // Microsoft Azure CLI, a first-party public client
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
      allowedMemberTypes: ['User', 'Application']
      isEnabled: true
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

output apiClientId string = app.appId
output tenantId string = tenant().tenantId
