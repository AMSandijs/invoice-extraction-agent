# Project Plan: Invoice Extraction & RAG Agent

## Vision

A fully cloud-native application where a user uploads invoice files and gets an intelligent chatbot that can answer questions about them — with no manual processing in between.

```
[ Upload invoices ]
        ↓
[ Azure AI Foundry processes them automatically ]
        ↓
[ Data stored + indexed ]
        ↓
[ RAG chatbot answers questions in plain English ]
```

---

## Current State (Phase 1 — Complete ✅)

A working local Python pipeline:

| File | What it does | Status |
|---|---|---|
| `extractor.py` | Extracts invoice data (Level 2 + 3) via GPT-4o | ✅ Done |
| `store.py` | Loads CSV into local SQLite database | ✅ Done |
| `agent.py` | Text-to-SQL conversational agent | ✅ Done |
| `app.py` | Streamlit browser chat UI | ✅ Done |

**What works right now**: point the extractor at a folder of invoices, load results into SQLite, and chat with the data via a local browser UI. Supports both Azure AI Foundry and standard OpenAI as the LLM provider.

**Current limitations**: everything runs locally, requires manual command-line steps, no file upload UI, database is a local SQLite file.

---

## Phase 2 — Azure-Native Backend 🔲

**Goal**: replace local scripts with Azure services so the pipeline runs automatically in the cloud.

### Architecture

```
Azure Blob Storage          ← user uploads invoices here
        ↓  (trigger)
Azure Function              ← runs on every new file upload
        ↓
Azure AI Foundry            ← GPT-4o extracts structured data
  └─ Document Intelligence  ← optional: pre-parse PDFs before GPT-4o
        ↓
Azure Cosmos DB             ← stores structured invoice records
        ↓
Azure AI Search             ← indexes records for semantic + keyword search
        ↓
Azure OpenAI (GPT-4o)       ← powers the RAG chatbot
```

### Key tasks

- Set up Azure Blob Storage container with upload trigger
- Write Azure Function (`process_invoice`) that calls AI Foundry on each new file
- Replace SQLite with Cosmos DB (NoSQL, fully managed, scales automatically)
- Set up Azure AI Search index over the Cosmos DB data
- Rewrite `agent.py` to use Azure AI Search for retrieval instead of Text-to-SQL
- Deploy everything via Azure Resource Manager (ARM) template or Bicep

### Why Azure AI Search instead of Text-to-SQL for Phase 2?

Text-to-SQL works well for precise structured queries ("total for Supplier X"). Azure AI Search adds:
- **Semantic search** — finds relevant invoices even with vague questions ("invoices from last quarter around €5k")
- **Hybrid retrieval** — combines keyword + vector search for best results
- **Scale** — handles millions of documents without query performance degradation

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
- **Cost controls**: set Azure budget alerts, cap AI Foundry token limits per user
- **Multi-tenancy**: isolate each organisation's invoices in separate Cosmos DB containers
- **Audit trail**: log every extraction + every chat query for compliance

---

## Phased Timeline Estimate

| Phase | Scope | Estimated effort |
|---|---|---|
| Phase 1 | Local pipeline (current) | ✅ Done |
| Phase 2 | Azure-native backend | 3–5 days |
| Phase 3 | Web application | 5–7 days |
| Phase 4 | Production hardening | 3–5 days |

Total to production-ready app from current state: **~2–3 weeks**

---

## Can it be made into an app?

Yes — and it's a natural progression from what already exists.

The Streamlit UI (`app.py`) is already a browser app. Deploying it to Azure App Service takes about 30 minutes and makes it accessible to anyone with a URL. That's the fastest path to a shareable demo.

For a proper product, Phase 3 describes the full React + FastAPI approach. The core intelligence (extraction via GPT-4o, RAG via Azure AI Search) stays the same — it just gets a proper frontend and API layer around it.

The entire stack is Azure-native, which means it integrates naturally with enterprise Microsoft environments (Azure AD, Teams, SharePoint) if that ever becomes relevant.

---

## Running cost estimate (production, small scale)

| Service | Usage assumption | Monthly cost |
|---|---|---|
| Azure AI Foundry (GPT-4o) | 500 invoices/month + 1,000 chat queries | ~$5–15 |
| Azure Blob Storage | 10 GB storage | ~$0.20 |
| Azure Cosmos DB | Serverless, low volume | ~$1–5 |
| Azure AI Search | Basic tier | ~$25 |
| Azure App Service | B1 tier | ~$13 |
| Azure Functions | Consumption plan, low volume | ~$0–1 |
| **Total** | | **~$45–60/month** |

For a demo or assignment context, everything can run on free tiers — cost is effectively $0.
