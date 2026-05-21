# Endpoints and names for wiring up the Phase 2 Function + agent code.
# No secrets — runtime access is via managed identity.

output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "function_app_name" {
  description = "Deploy code with: func azure functionapp publish <this>"
  value       = azurerm_linux_function_app.func.name
}

output "storage_account_name" {
  value = azurerm_storage_account.sa.name
}

output "blob_container" {
  value = azurerm_storage_container.invoices.name
}

output "openai_endpoint" {
  value = azurerm_cognitive_account.openai.endpoint
}

output "gpt4o_deployment" {
  value = azurerm_cognitive_deployment.gpt4o.name
}

output "embedding_deployment" {
  value = azurerm_cognitive_deployment.embedding.name
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.cosmos.endpoint
}

output "cosmos_database" {
  value = azurerm_cosmosdb_sql_database.db.name
}

output "cosmos_container" {
  value = azurerm_cosmosdb_sql_container.records.name
}

output "search_endpoint" {
  value = "https://${azurerm_search_service.search.name}.search.windows.net"
}

output "search_index" {
  description = "Index name the Function/agent should create and query."
  value       = "invoices-idx"
}

output "app_url" {
  description = "Public HTTPS URL for the hosted Streamlit Invoice Assistant."
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "acr_name" {
  description = "Container registry name — used by deploy.sh for az acr build."
  value       = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  description = "Full registry hostname — used to tag and reference images."
  value       = azurerm_container_registry.acr.login_server
}

output "container_app_name" {
  description = "Container App name — used by deploy.sh for az containerapp update."
  value       = azurerm_container_app.app.name
}
