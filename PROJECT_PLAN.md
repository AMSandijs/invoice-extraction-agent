# Project Plan: Invoice Extraction & RAG Agent

## Vision

A fully cloud-native application where a user uploads invoice files and gets an intelligent chatbot that can answer questions about them — with no manual processing in between.

```
[ Upload invoices ]
        ↓
[ Azure Function processes them automatically ]
        ↓
[ Data stored + indexed ]
        ↓
[ RAG chatbot answers questions in plain English ]
```

---

## Phase 1 — Local pipeline ✅ Complete

A working local Python pipeline for invoice extraction.

| File | What it does | Status |
|---|---|---|
| `extractor.py` | Extracts invoice data via GPT-4o (text + vision paths) | ✅ Done |
| `store.py` | Legacy: loads CSV into local SQLite. Retained for reference; not used by the RAG agent. | ✅ Done |
| `agent.py` | RAG agent — hybrid retrieval over Azure AI Search + GPT-4o | ✅ Done |
| `app.py` | Streamlit browser chat UI for the RAG agent | ✅ Done |

**What works**: point the extractor at a folder of invoices → CSV output. Supports both Azure OpenAI and standard OpenAI as the LLM provider. Auto-detects text PDF, scanned PDF, or image inputs.

---

## Phase 2 — Azure-Native Backend ✅ Complete

**Goal**: replace local scripts with Azure services so the pipeline runs automatically in the cloud.

### Architecture deployed

```
Azure Blob Storage (invoices container)
        ↓  blob trigger
Azure Function  process_invoice
        ↓  GPT-4o extraction (text + vision)
Azure Cosmos DB        ← structured invoice records
        ↓
Azure AI Search        ← hybrid keyword + vector index
        ↓
RAG agent (agent.py)   ← AI Search retrieval + GPT-4o → Streamlit chat (app.py)
```

Resource-to-resource calls use managed identity; no keys are stored.

### What was built

- ✅ OpenTofu IaC for all resources (Blob Storage, Function App, Azure OpenAI, Cosmos DB, AI Search)
- ✅ Azure Function `process_invoice` — blob-triggered, GPT-4o extraction, writes to Cosmos DB + AI Search
- ✅ `agent.py` rewritten as a hybrid-RAG agent (keyword + VectorizedQuery, top=50, multi-turn history)
- ✅ `app.py` updated: Search reachability check, stats from index, "Retrieved invoices" expander
- ✅ `infra/rbac.tf` — `Search Index Data Reader` + `Cognitive Services OpenAI User` role assignments per agent user
- ✅ Unit tests (9 tests) with mocked Azure clients, all passing
- ✅ Auth: `DefaultAzureCredential` (AAD via `az login`); no secrets on disk

### Why Azure AI Search instead of Text-to-SQL?

Text-to-SQL works well for precise structured queries. Azure AI Search adds:
- **Hybrid retrieval** — combines keyword + vector search for best results
- **Scale** — handles large document sets without schema migrations
- **Vague queries** — finds relevant invoices even with natural-language questions

---

## Phase 3 — Full Web Application 🔲

**Goal**: a proper web app any user can open in a browser, upload invoices, and start chatting — no terminal, no scripts.

### Tech options

| Approach | Effort | Best for |
|---|---|---|
| **Streamlit on Azure App Service** | Low | Quick demo, internal tool |
| **React + FastAPI on Azure App Service** | Medium | Polished product, full control |
| **Power Apps + Power Automate** | Low-Medium | Microsoft-stack organisations |

### Recommended: React frontend + FastAPI backend

```
Browser (React)
  │   ├── Invoice upload page  →  POST /api/upload  →  Azure Blob
  │   ├── Processing status    →  GET  /api/status
  │   └── Chat interface       →  POST /api/chat    →  RAG agent
  │
Azure App Service (FastAPI)
  ├── /api/upload      → writes to Blob Storage
  ├── /api/status      → reads from Cosmos DB
  └── /api/chat        → queries Azure AI Search + GPT-4o
```

**Authentication**: Azure Active Directory / Entra ID (enterprise SSO, free tier available)

**Hosting**: Azure App Service (B1 tier ~$13/month, or free tier for demo)

---

## Phase 4 — Production Hardening 🔲

- **CI/CD**: GitHub Actions → Azure App Service (auto-deploy on push to `main`)
- **Monitoring**: Azure Application Insights (errors, latency, cost tracking)
- **Cost controls**: set Azure budget alerts, cap OpenAI token limits per user
- **Multi-tenancy**: isolate each organisation's invoices in separate Cosmos DB containers
- **Audit trail**: log every extraction + every chat query for compliance

---

## Phased Timeline Estimate

| Phase | Scope | Estimated effort |
|---|---|---|
| Phase 1 | Local pipeline | ✅ Done |
| Phase 2 | Azure-native backend + RAG agent | ✅ Done |
| Phase 3 | Web application | 5–7 days |
| Phase 4 | Production hardening | 3–5 days |

---

## Running cost estimate (production, small scale)

| Service | Usage assumption | Monthly cost |
|---|---|---|
| Azure OpenAI (GPT-4o) | 500 invoices/month + 1,000 chat queries | ~$5–15 |
| Azure Blob Storage | 10 GB storage | ~$0.20 |
| Azure Cosmos DB | Serverless, low volume | ~$1–5 |
| Azure AI Search | Free tier (demo) / Basic tier (prod) | $0 / ~$25 |
| Azure App Service | B1 tier | ~$13 |
| Azure Functions | Consumption plan, low volume | ~$0–1 |
| **Total** | | **~$45–60/month** |

For a demo or assignment context, everything runs on free/serverless tiers — cost is effectively $0.
