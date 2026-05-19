# Phase 2 RAG Agent — Design

**Date:** 2026-05-19
**Status:** Approved
**Supersedes:** Phase 1 Text-to-SQL agent (`agent.py` + `app.py` against local SQLite)

---

## 1. Goal

Replace the Phase 1 Text-to-SQL agent with a hybrid-RAG agent that answers
natural-language questions about invoices by retrieving from the Azure AI
Search index (`invoices-idx`) populated by the Phase 2 ingestion Function.

The SQLite path is removed entirely — no Phase 1 fallback.

---

## 2. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Retrieval strategy | Hybrid RAG, big top-k | Keyword + vector retrieval with `top=50`; returns the whole dataset at demo scale, so the LLM can aggregate in-prompt. Degrades gracefully to "most relevant 50" if data grows. |
| Aggregate questions | Handled in-prompt | "Total across all invoices", "highest supplier", "average" — answered by the LLM over the retrieved set, not by a query engine. Acceptable because `top=50` ≥ dataset size at demo scale. |
| Hosting | Local Streamlit | `app.py` stays a local app pointed at cloud endpoints. No new hosting infra. |
| Auth | AAD via `DefaultAzureCredential` | No secrets on disk. Per-user access via Azure RBAC; scale-out to a hosted managed identity needs zero code change. |
| SQLite | Removed | Data now lives in AI Search; Phase 1 store is dead. |

---

## 3. Architecture & Data Flow

```
User question (Streamlit chat)
   │
   ▼
InvoiceAgent.ask(question)
   │
   ├─ 1. embed(question)  ──────────►  Azure OpenAI  text-embedding-3-large
   │                                  → query vector (3072-dim)
   │
   ├─ 2. hybrid search   ──────────►  Azure AI Search  invoices-idx
   │      keyword on `content`
   │      + VectorizedQuery on `content_vector`
   │      top=50, select all structured fields + content
   │      → list[invoice doc]
   │
   ├─ 3. answer prompt   ──────────►  Azure OpenAI  gpt-4o
   │      system prompt + retrieved invoices + recent chat history
   │      → natural-language answer
   │
   ▼
AgentResponse(answer, results, error)
```

The index has **no integrated vectorizer** (see `function_app/search_indexer.py`),
so the question must be embedded client-side and passed as a `VectorizedQuery`
— the same pattern the ingestion Function uses.

---

## 4. Components

### 4.1 `agent.py` (rewrite)

Drop all SQL/SQLite logic. New shape:

- **`get_credential()`** — returns a cached `DefaultAzureCredential`.
- **Client factory** — builds:
  - `SearchClient(endpoint, index_name, credential)` for retrieval.
  - `AzureOpenAI(..., azure_ad_token_provider=...)` using
    `get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")`
    for both chat and embedding calls.
- **`retrieve(question) -> list[dict]`** — embeds the question, runs the hybrid
  query (keyword + `VectorizedQuery`), returns retrieved invoice docs with
  structured fields + `content` (never `content_vector`).
- **`InvoiceAgent`**
  - `__init__` — builds clients from env config; raises `EnvironmentError`
    with a clear message if required env vars are missing.
  - `ask(question) -> AgentResponse` — retrieve, then generate the answer.
    Every question goes through retrieve→answer; greetings/conversational
    messages are handled naturally by the answer prompt (no separate branch).
  - Multi-turn: keeps recent chat history and passes it into the answer
    prompt so follow-ups ("what about in USD?") resolve correctly.
  - `get_stats() -> dict` — index doc count + distinct currencies via a
    Search facet query (replaces the SQLite stats query).
- **`AgentResponse`** dataclass — `answer: str`, `results: list | None`
  (the retrieved invoice docs), `error: str | None`. The `sql` field is removed.

### 4.2 `app.py` (update)

Keep the Streamlit chat UI structure. Changes:

- **Status block** — replace the "database file exists?" check with an AI
  Search reachability check (index responds + doc count).
- **Sidebar stats** — driven by `get_stats()` (Search facets), not SQL.
- **Expander** — "SQL query used" → "Retrieved invoices" showing the docs
  the answer was grounded in.
- **Error/setup messaging** — replace SQLite/`extractor.py` instructions with
  `.env` endpoint setup + `az login` guidance.
- The `--db` CLI argument is removed.

### 4.3 `infra/rbac.tf` (update)

Add a variable and role assignments so agent users get data-plane access:

- **`variable "agent_user_object_ids"`** — `list(string)`, default `[]`.
  Azure AD object IDs of users allowed to run the agent.
- For each object ID, create two role assignments:
  - `Search Index Data Reader` scoped to the Search service.
  - `Cognitive Services OpenAI User` scoped to the Azure OpenAI account.
- Populated in `terraform.tfvars`; each user finds their ID via
  `az ad signed-in-user show --query id -o tsv`.

### 4.4 `requirements.txt` (update)

- Add `azure-search-documents>=11.5.0`, `azure-identity>=1.17.0`, and
  `python-dotenv>=1.0.0`.
- Remove the SQLite note. Extraction deps stay (extractor.py is Phase 1, untouched).

### 4.5 Config

A gitignored `.env` (already covered by `.gitignore`) holds **endpoints only —
no secrets**, sourced from `tofu output`:

| Var | Source |
|-----|--------|
| `SEARCH_ENDPOINT` | `tofu output search_endpoint` |
| `SEARCH_INDEX` | `invoices-idx` |
| `AZURE_OPENAI_ENDPOINT` | `tofu output openai_endpoint` |
| `AZURE_OPENAI_GPT_DEPLOYMENT` | `gpt-4o` |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `text-embedding-3-large` |
| `AZURE_OPENAI_API_VERSION` | `2024-12-01-preview` |

A `.env.sample` documents these. `agent.py` loads them with `python-dotenv`
(`load_dotenv()` at import time).

---

## 5. Error Handling

| Condition | Behavior |
|-----------|----------|
| Required env var missing | `InvoiceAgent.__init__` raises `EnvironmentError`; `app.py` shows a setup message in the sidebar. |
| Search index unreachable / auth failure | `ask()` returns `AgentResponse` with a friendly message + `error` populated. |
| Index empty (0 docs) | Answer states no invoices are indexed yet. |
| Embedding or chat call fails | `ask()` degrades gracefully — returns the retrieved docs (if any) with an error note. |

---

## 6. Testing

Unit tests with the Search and Azure OpenAI clients mocked (no live calls):

- `retrieve()` builds a hybrid query — keyword text **and** a `VectorizedQuery`
  on `content_vector` — with `top=50` and the expected `select` fields.
- `ask()` returns the model's answer for a normal question.
- `ask()` handles an empty index (0 retrieved docs).
- `ask()` handles a retrieval failure (Search client raises).
- `ask()` handles an answer-generation failure (chat call raises) — returns
  retrieved docs + error.
- `get_stats()` parses facet results into the expected dict.

Tests live in a new repo-root `tests/` directory (`tests/test_agent.py`) —
the existing `function_app/tests/` covers the ingestion side only.

---

## 7. Out of Scope

- Hosting the agent in Azure (App Service / Container App) — deferred to a
  future scale-out; `DefaultAzureCredential` makes that a no-code-change move.
- Semantic ranker — not available on the Search Free tier.
- Changes to the ingestion Function or `extractor.py`.
- Re-ranking, query rewriting, or citation UI beyond the "Retrieved invoices"
  expander.
