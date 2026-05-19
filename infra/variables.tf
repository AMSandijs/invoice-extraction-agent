variable "subscription_id" {
  description = "Target Azure subscription — PCO sbal Sandbox."
  type        = string
  default     = "21a1faed-77bc-4545-a743-eda9becaebc6"
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "swedencentral"
}

variable "name_prefix" {
  description = "Prefix used to name resources. Lowercase, hyphen-separated."
  type        = string
  default     = "invoice-rag"
}

variable "gpt4o_model_version" {
  description = "GPT-4o model version to deploy."
  type        = string
  default     = "2024-11-20"
}

variable "gpt4o_capacity" {
  description = "GPT-4o deployment capacity, in thousands of tokens-per-minute (limit: 150)."
  type        = number
  default     = 50
}

variable "embedding_model_version" {
  description = "text-embedding-3-large model version."
  type        = string
  default     = "1"
}

variable "embedding_capacity" {
  description = "Embedding deployment capacity, in thousands of TPM."
  type        = number
  default     = 50
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project     = "invoice-rag"
    phase       = "phase-2"
    environment = "sandbox"
    managed-by  = "opentofu"
  }
}
