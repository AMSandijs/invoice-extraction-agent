# Phase 2 — Azure Deployment Plan

**Status:** Draft for review — no resources created yet.
**Target subscription:** `PCO sbal Sandbox` — `21a1faed-77bc-4545-a743-eda9becaebc6`
**Tenant:** `887779d5-5770-4d6c-82f2-a2b26e750177` · **Account:** sandijs.balodis@atea.com
**Region:** Sweden Central · **IaC:** OpenTofu/Terraform · **Profile:** Lean / free-tier

---

## 1. Scope

Replace the local Phase 1 pipeline (`extractor.py` → `store.py` → SQLite) with an
Azure-native backend: invoices uploaded to Blob Storage trigger a Function that
extracts data via GPT-4o, writes to Cosmos DB, and exposes the data through AI Search
for the RAG agent.

**Document Intelligence is intentionally excluded** — GPT-4o Vision already handles
scanned PDFs in Phase 1, so it adds cost without adding capability here.

---

## 2. Resources to deploy

All in one new resource group: **`rg-invoice-rag`** (Sweden Central).

| # | Resource | Name (proposed) | SKU / tier | Idle cost |
|---|----------|-----------------|------------|-----------|
| 1 | Resource Group | `rg-invoice-rag` | — | — |
| 2 | Storage Account | `stinvoicerag<suffix>` | Standard LRS, Hot | ~$0 |
| 3 | Blob container | `invoices` | — | — |
| 4 | Log Analytics workspace | `log-invoice-rag` | PerGB2018 | ~$0 (5GB free) |
| 5 | Application Insights | `appi-invoice-rag` | workspace-based | ~$0 |
| 6 | Function App plan | `plan-invoice-rag` | Consumption (Y1, Linux) | $0 |
| 7 | Function App | `func-invoice-rag` | Python 3.11 | pay-per-exec (~$0) |
| 8 | Azure OpenAI account | `aoai-invoice-rag` | kind `OpenAI`, S0 | $0 idle |
| 9 | — GPT-4o deployment | `gpt-4o` | Standard, quota-dependent | pay-per-token |
| 10 | Cosmos DB account | `cosmos-invoice-rag` | NoSQL API, **Serverless** | ~$0 idle |
| 11 | — Database / container | `invoices` / `records` (PK `/supplier_name`) | — | — |
| 12 | Azure AI Search | `srch-invoice-rag` | **Free** tier | $0 |

`<suffix>` = short random string — storage / Cosmos / Search names are globally unique.

**Estimated cost:** ~$0/month idle; ~$5–15/month for ~500 invoices + chat traffic
(GPT-4o tokens only). Sandbox has a budget-alert RG already — spend here is negligible.

---

## 3. Authentication model

**No secrets in app settings.** The Function App gets a **system-assigned managed
identity**, granted data-plane RBAC roles:

| Target | Role |
|--------|------|
| Storage account | Storage Blob Data Contributor |
| Cosmos DB | Cosmos DB Built-in Data Contributor (SQL role) |
| AI Search | Search Index Data Contributor + Search Service Contributor |
| Azure OpenAI | Cognitive Services OpenAI User |

**Terraform/OpenTofu auth:** your existing `az login` session (sandijs.balodis@atea.com)
— no service principal needed for the sandbox.

---

## 4. About the "env keys"

For Phase 2 there are **no Azure resource keys to provide up front** — endpoints and
keys are *outputs* of this deployment, not inputs, and resource-to-resource calls use
managed identity.

The only thing worth deciding before `apply`:

- **Create a fresh `aoai-invoice-rag`** (clean Terraform-managed state) — *recommended*, OR
- **Reuse the existing `invoice-auto` AIServices account** (already in Sweden Central,
  no GPT-4o deployment yet) — avoids a second quota request but lives outside this
  Terraform state.

If you have a GPT-4o-enabled Foundry/OpenAI resource elsewhere with spare quota, that
endpoint + key is the only credential worth supplying. Otherwise: nothing needed.

---

## 5. Terraform layout

New `infra/` folder in the homework repo:

```
infra/
  versions.tf       # opentofu >= 1.6, azurerm ~> 3.x
  providers.tf      # azurerm, subscription_id pinned to the sandbox
  variables.tf      # region, name prefix, gpt-4o capacity
  main.tf           # RG, storage, log/appinsights, function, cosmos, search
  openai.tf         # AOAI account + gpt-4o deployment
  rbac.tf           # role assignments for the Function managed identity
  outputs.tf        # endpoints + resource names (no secrets)
  terraform.tfvars  # concrete values
```

**State backend:** local state for the demo (simplest). Optional: remote state in the
existing `rg-terraform-state` — say the word and I'll wire the `azurerm` backend block.

---

## 6. Deployment steps

1. **Review & approve this plan** ← you are here
2. Pre-flight check: GPT-4o Standard quota in Sweden Central
   (`az cognitiveservices usage list -l swedencentral`) and confirm no existing
   free-tier AI Search service in the subscription.
3. I write the `infra/` Terraform files.
4. `cd infra && tofu init`
5. `tofu plan` — review the resource graph together.
6. `tofu apply` — provisions everything (~5–10 min; the GPT-4o deployment is slowest).
7. Capture `tofu output` → endpoints for the Function app settings.
8. **(Phase 2 code work, separate)** rewrite `process_invoice` as a blob-triggered
   Function, point `agent.py` at AI Search, deploy via `func azure functionapp publish`.
9. Smoke test: upload a sample invoice → Function fires → record in Cosmos →
   index populated → agent answers a question.

---

## 7. Risks & caveats

| Risk | Mitigation |
|------|-----------|
| GPT-4o Standard quota in sandbox may be 0 | Step 2 pre-flight check; reuse `invoice-auto` or request quota if blocked |
| AI Search Free tier — only 1 per subscription | Verify none exists before apply |
| Cosmos free tier already consumed | Using Serverless instead — confirmed in plan |
| Storage/Cosmos/Search global name collisions | Random suffix on all three |
| Sandbox auto-cleanup policies | Costs are negligible; tag resources `project=invoice-rag` |

---

## 8. Open question for you

- **Fresh `aoai-invoice-rag`** vs **reuse `invoice-auto`** for the GPT-4o resource?
  (Section 4 — recommendation: fresh, for clean Terraform state.)
