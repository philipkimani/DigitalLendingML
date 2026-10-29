// DigitalLendingML dev environment. Deploy into an existing resource group:
//   az deployment group create -g rg-digitallending-dev -f infra/main.bicep \
//     -p adminObjectId=<entra object id> adminName=<upn>
// No secrets: Postgres is Entra-only, services use the user-assigned managed identity.

param location string = resourceGroup().location
param env string = 'dev'

@description('Entra object id of the human Postgres admin. Passed at deploy time, never committed.')
param adminObjectId string
@description('UPN of that admin.')
param adminName string

param amlVmSize string = 'Standard_DS2_v2' // 2 vCPU; 2 nodes fit the default 4-core regional quota
param apiImage string = 'mcr.microsoft.com/k8se/quickstart:latest' // ponytail: placeholder until the API image exists in ACR

var name = 'digitallending-${env}'
var suffix = take(uniqueString(resourceGroup().id), 6)
var tenantId = subscription().tenantId

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-dl${env}${suffix}'
  location: location
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource st 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stdl${env}${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crdl${env}${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// Azure ML (Foundry) workspace: jobs, schedules, MLflow tracking, model registry.
resource mlw 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: 'mlw-${name}'
  location: location
  sku: { name: 'Basic', tier: 'Basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    friendlyName: 'DigitalLendingML ${env}'
    storageAccount: st.id
    keyVault: kv.id
    applicationInsights: appi.id
    containerRegistry: acr.id
    publicNetworkAccess: 'Enabled' // dev stopgap; prod uses managed VNet (docs/architecture.md)
  }
}

resource cluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01' = {
  parent: mlw
  name: 'cpu-cluster'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: amlVmSize
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0 // pay only while a job runs
        maxNodeCount: 2
        nodeIdleTimeBeforeScaleDown: 'PT5M'
      }
    }
  }
}

resource psql 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-${name}-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    storage: { storageSizeGB: 32 }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenantId
    }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' } // dev stopgap; prod uses private access
  }
}

resource psqlAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: psql
  name: adminObjectId
  properties: {
    principalType: 'User'
    principalName: adminName
    tenantId: tenantId
  }
}

resource psqlAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: psql
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [ psqlAdmin ] // server rejects concurrent child updates
}

resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: psql
  name: 'lending'
  dependsOn: [ psqlAzure ]
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: { external: true, targetPort: 80, transport: 'auto' }
      registries: [ { server: acr.properties.loginServer, identity: uami.id } ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'PGHOST', value: psql.properties.fullyQualifiedDomainName }
            { name: 'PGDATABASE', value: db.name }
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
  dependsOn: [ acrPull ]
}

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUserRole = '4633458b-17de-408a-b874-0445c86b69e6' // gitleaks:allow built-in Azure role id (public, same in every tenant)

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, uami.id, acrPullRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, uami.id, kvSecretsUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRole)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The identity gets a least-privilege Postgres role via a SQL migration (pgaadauth_create_principal), not admin.
output identityName string = uami.name
output identityClientId string = uami.properties.clientId
output postgresHost string = psql.properties.fullyQualifiedDomainName
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output mlWorkspace string = mlw.name
output acrLoginServer string = acr.properties.loginServer
