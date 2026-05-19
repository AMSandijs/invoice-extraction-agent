# ADR-0003: Managed identity authentication — no secrets on disk

**Date:** 2026-05-19  
**Status:** Accepted

## Context

The Phase 2 system makes calls between several Azure services (Function → Cosmos DB, Function → AI Search, agent → AI Search, agent → Azure OpenAI). Each call must be authenticated. The straightforward approach is to generate API keys or connection strings and paste them into environment variables or app settings.

Alternatives considered:

| Approach | Pros | Cons |
|---|---|---|
| API keys / connection strings in env vars | Simple to set up | Keys rotate manually; leak risk if committed; violates zero-trust |
| API keys in Azure Key Vault | Keys never in code | Still requires bootstrapping a Key Vault identity; adds a service |
| Managed identity (system-assigned) | No credentials to manage; automatic rotation | Requires RBAC assignments per principal |
| `DefaultAzureCredential` (user identity) | Works locally with `az login`; same code in production | User must have correct RBAC roles granted |

## Decision

Use managed identity throughout:

- **Function App → Cosmos DB and AI Search**: system-assigned managed identity with `Cosmos DB Built-in Data Contributor` and `Search Index Data Contributor` role assignments (provisioned in `infra/rbac.tf`).
- **Agent (local) → AI Search and Azure OpenAI**: `DefaultAzureCredential` authenticated via `az login`. The token provider uses `get_bearer_token_provider` from `azure-identity`, which handles token refresh automatically.
- **`.env` contains endpoints only** — no keys, no secrets. The file is gitignored. `.env.sample` (tracked) documents the required variable names.

RBAC roles for agent users are declared in `infra/variables.tf` (`agent_user_object_ids`) and applied in `infra/rbac.tf`, so access is managed as infrastructure rather than shared credentials.

## Consequences

- **No secrets on disk or in git** — eliminates the most common credential-leak vector.
- **Zero code change to host the agent** — `DefaultAzureCredential` picks up a managed identity automatically when running in Azure App Service or Container Apps.
- **RBAC as the access control plane** — revoking a user's access is one `tofu apply`, not a key rotation.
- **`az login` required locally** — developers must authenticate before running the agent. Documented in the README.
- **Role propagation delay** — new RBAC assignments can take up to a few minutes to take effect in Azure.
