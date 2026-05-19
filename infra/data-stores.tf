# --- Cosmos DB: structured invoice records -------------------------------
# Serverless — the free tier is already used by another account in this
# subscription, and serverless is ~$0 idle at demo volume anyway.

resource "azurerm_cosmosdb_account" "cosmos" {
  name                = "cosmos-${var.name_prefix}-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  free_tier_enabled   = false

  capabilities {
    name = "EnableServerless"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  tags = var.tags
}

resource "azurerm_cosmosdb_sql_database" "db" {
  name                = "invoices"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.cosmos.name
}

resource "azurerm_cosmosdb_sql_container" "records" {
  name                  = "records"
  resource_group_name   = azurerm_resource_group.rg.name
  account_name          = azurerm_cosmosdb_account.cosmos.name
  database_name         = azurerm_cosmosdb_sql_database.db.name
  partition_key_paths   = ["/supplier_name"]
  partition_key_version = 2
}

# --- Azure AI Search: semantic + hybrid retrieval over invoices ----------

resource "azurerm_search_service" "search" {
  name                         = "srch-${var.name_prefix}-${local.suffix}"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  sku = "free"
  # Semantic ranker (semantic_search_sku) requires Basic tier or higher —
  # omitted here. Hybrid keyword + vector retrieval still works on Free.
  local_authentication_enabled = true
  # Allow both API key and AAD token (managed identity) authentication.
  authentication_failure_mode  = "http401WithBearerChallenge"

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}
