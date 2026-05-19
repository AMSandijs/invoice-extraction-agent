# --- Azure OpenAI (fresh account, Terraform-managed) ---------------------

resource "azurerm_cognitive_account" "openai" {
  name                  = "aoai-${var.name_prefix}-${local.suffix}"
  resource_group_name   = azurerm_resource_group.rg.name
  location              = azurerm_resource_group.rg.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "aoai-${var.name_prefix}-${local.suffix}"
  tags                  = var.tags
}

# GPT-4o — invoice extraction + RAG chat completion.
resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = var.gpt4o_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.gpt4o_capacity
  }
}

# text-embedding-3-large — vector embeddings for AI Search hybrid retrieval.
resource "azurerm_cognitive_deployment" "embedding" {
  name                 = "text-embedding-3-large"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "text-embedding-3-large"
    version = var.embedding_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.embedding_capacity
  }

  # Serialize deployment creation — same parent account.
  depends_on = [azurerm_cognitive_deployment.gpt4o]
}
