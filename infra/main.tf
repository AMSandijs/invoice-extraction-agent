locals {
  # Storage / Cosmos / Search names must be globally unique and alphanumeric-ish.
  name_clean = replace(var.name_prefix, "-", "")
  suffix     = random_string.suffix.result
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

# --- Resource group ------------------------------------------------------

resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = var.tags
}

# --- Storage: invoice uploads + Function backing store -------------------

resource "azurerm_storage_account" "sa" {
  name                            = "st${local.name_clean}${local.suffix}"
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = var.tags
}

# Upload target — a new blob here fires the process_invoice Function.
resource "azurerm_storage_container" "invoices" {
  name                  = "invoices"
  storage_account_name  = azurerm_storage_account.sa.name
  container_access_type = "private"
}

# --- Observability -------------------------------------------------------

resource "azurerm_log_analytics_workspace" "law" {
  name                = "log-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_application_insights" "ai" {
  name                = "appi-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = var.tags
}

# --- Function App: process_invoice (blob trigger) ------------------------

resource "azurerm_service_plan" "plan" {
  name                = "plan-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "Y1" # Consumption — pay per execution
  tags                = var.tags
}

resource "azurerm_linux_function_app" "func" {
  name                = "func-${var.name_prefix}-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id

  storage_account_name       = azurerm_storage_account.sa.name
  storage_account_access_key = azurerm_storage_account.sa.primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.ai.connection_string
    application_stack {
      python_version = "3.11"
    }
  }

  # Endpoints only — no secrets. Resource access uses the managed identity.
  app_settings = {
    AzureWebJobsFeatureFlags          = "EnableWorkerIndexing"
    AZURE_OPENAI_ENDPOINT             = azurerm_cognitive_account.openai.endpoint
    AZURE_OPENAI_GPT_DEPLOYMENT       = azurerm_cognitive_deployment.gpt4o.name
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = azurerm_cognitive_deployment.embedding.name
    AZURE_OPENAI_API_VERSION          = "2024-12-01-preview"
    COSMOS_ENDPOINT                   = azurerm_cosmosdb_account.cosmos.endpoint
    COSMOS_DATABASE                   = azurerm_cosmosdb_sql_database.db.name
    COSMOS_CONTAINER                  = azurerm_cosmosdb_sql_container.records.name
    SEARCH_ENDPOINT                   = "https://${azurerm_search_service.search.name}.search.windows.net"
    SEARCH_INDEX                      = "invoices-idx"
  }

  tags = var.tags
}
