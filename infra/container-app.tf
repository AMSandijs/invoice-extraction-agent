# --- Azure Container Registry: stores the Streamlit app image -----------

resource "azurerm_container_registry" "acr" {
  name                = "cr${local.name_clean}${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

# --- Container Apps Environment ------------------------------------------

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${var.name_prefix}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = var.tags
}

# --- Container App: Streamlit web UI -------------------------------------
# Image is managed by deploy.sh (az acr build + az containerapp update).
# lifecycle.ignore_changes on the image prevents tofu apply from resetting
# it back to the placeholder after the deploy script has updated it.

resource "azurerm_container_app" "app" {
  name                         = "ca-${var.name_prefix}"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = true
    target_port      = 8501
    transport        = "auto"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "invoice-agent"
      # Placeholder — replaced by deploy.sh after the image is built.
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = "2024-12-01-preview"
      }
      env {
        name  = "AZURE_OPENAI_GPT_DEPLOYMENT"
        value = azurerm_cognitive_deployment.gpt4o.name
      }
      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = azurerm_cognitive_deployment.embedding.name
      }
      env {
        name  = "STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.sa.name
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.cosmos.endpoint
      }
      env {
        name  = "COSMOS_DATABASE"
        value = azurerm_cosmosdb_sql_database.db.name
      }
      env {
        name  = "COSMOS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.records.name
      }
      env {
        name  = "SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }
      env {
        name  = "SEARCH_INDEX"
        value = "invoices-idx"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  tags = var.tags
}
