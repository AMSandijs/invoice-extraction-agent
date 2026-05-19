# ADR-0004: OpenTofu for infrastructure-as-code

**Date:** 2026-05-19  
**Status:** Accepted

## Context

Phase 2 requires provisioning ~8 Azure resources (resource group, Storage, Function App, Azure OpenAI, Cosmos DB, AI Search, plus RBAC role assignments). These need to be repeatable and reviewable.

Alternatives considered:

| Approach | Pros | Cons |
|---|---|---|
| Azure Portal (manual) | Fastest to start | Not reproducible; no version control; error-prone |
| Azure CLI scripts | Version-controlled; scriptable | Imperative; no state tracking; hard to update/destroy cleanly |
| Bicep | Native Azure DSL; first-class ARM support | Azure-only; less portable; smaller community tooling |
| Terraform (HashiCorp) | Mature; large ecosystem | BSL licence since 1.6 |
| OpenTofu | Terraform-compatible; OSS (MPL-2.0) | Newer project; fewer providers than Terraform (but azurerm is supported) |

## Decision

Use OpenTofu with the `hashicorp/azurerm` provider. The configuration lives in `infra/` and is applied with `tofu init / plan / apply`.

All resources are tagged and grouped in a single resource group (`rg-invoice-rag`). `tofu output` exposes the endpoints needed by the agent's `.env` file.

## Consequences

- **Reproducible deploys** — any reviewer can `tofu apply` and get an identical environment.
- **Explicit destroy** — `tofu destroy` tears down all resources cleanly; no orphaned services.
- **State file not committed** — `terraform.tfstate` is gitignored. For production, state should be stored in an Azure Storage backend; for this assignment, local state is sufficient.
- **`terraform.tfvars` committed** — contains object IDs for RBAC assignments (not secrets). Reviewers can see who has access.
- **OpenTofu vs Terraform** — the `azurerm` provider works identically under both; switching back to Terraform requires only renaming the binary.
