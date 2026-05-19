# Role assignments granting the Function App's managed identity data-plane
# access to each backend service. No keys are stored anywhere.

locals {
  func_principal_id = azurerm_linux_function_app.func.identity[0].principal_id
}

# --- Storage: read invoice blobs -----------------------------------------
resource "azurerm_role_assignment" "func_storage_blob" {
  scope                = azurerm_storage_account.sa.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = local.func_principal_id
}

# --- Azure OpenAI: call GPT-4o + embeddings ------------------------------
resource "azurerm_role_assignment" "func_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = local.func_principal_id
}

# --- AI Search: create/query indexes and push documents ------------------
resource "azurerm_role_assignment" "func_search_service" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = local.func_principal_id
}

resource "azurerm_role_assignment" "func_search_data" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = local.func_principal_id
}

# --- Cosmos DB: data-plane access (SQL role, not Azure RBAC) -------------
resource "azurerm_cosmosdb_sql_role_assignment" "func_cosmos" {
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  # Built-in "Cosmos DB Built-in Data Contributor" role.
  role_definition_id = "${azurerm_cosmosdb_account.cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id       = local.func_principal_id
  scope              = azurerm_cosmosdb_account.cosmos.id
}

# --- Agent users: data-plane read access for the local RAG agent ---------
# Each listed user can query AI Search and call Azure OpenAI as themselves.

resource "azurerm_role_assignment" "agent_search_read" {
  for_each             = toset(var.agent_user_object_ids)
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "agent_openai_user" {
  for_each             = toset(var.agent_user_object_ids)
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = each.value
}
