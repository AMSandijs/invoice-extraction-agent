# ADR-0002: Hybrid RAG over Azure AI Search instead of Text-to-SQL

**Date:** 2026-05-19  
**Status:** Accepted  
**Supersedes:** Phase 1 Text-to-SQL agent against local SQLite

## Context

The Phase 1 agent converted natural-language questions to SQL and queried a local SQLite database. This worked for precise structured questions ("total for Supplier X") but had weaknesses:

- SQL generation fails or produces wrong results for vague questions ("invoices around €5k from last quarter").
- SQLite is local — no shared access, no upload trigger, not cloud-native.
- A Text-to-SQL approach exposes the schema to the LLM and trusts it to generate correct SQL, which is fragile for aggregations and joins.

Alternatives considered:

| Approach | Pros | Cons |
|---|---|---|
| Text-to-SQL (SQLite) | Simple, no extra services | Fails on vague queries; local only |
| Text-to-SQL (Azure SQL) | Cloud-hosted | Same fragility; adds a relational DB to manage |
| Pure vector search | Good semantic recall | Misses exact-match keyword queries (invoice numbers, supplier names) |
| Hybrid RAG (keyword + vector) | Best recall for both precise and vague queries | Requires embedding at ingest and query time |

## Decision

Replace the Text-to-SQL agent with a hybrid-RAG agent backed by Azure AI Search:

- **Ingest**: the Azure Function embeds each invoice summary (`text-embedding-3-large`, 3072-dim) and writes both the structured fields and the vector to the AI Search index.
- **Retrieve**: at query time, embed the question client-side and issue a hybrid search — keyword on `content` plus a `VectorizedQuery` on `content_vector` — with `top=50`.
- **Generate**: pass all 50 retrieved documents to GPT-4o with a system prompt. At demo scale, 50 records covers the full dataset, so aggregate questions ("highest supplier", "total spend") are answered in-prompt without a separate aggregation layer.

## Consequences

- **Better recall on vague questions** — hybrid search finds records that keyword-only or vector-only would miss.
- **Aggregate answers work at demo scale** — `top=50` returns the whole dataset; GPT-4o computes totals/averages in-prompt. This degrades gracefully to "most relevant 50" if data grows beyond 50 records, which is acceptable for this assignment.
- **No semantic ranker** — not available on the Azure AI Search Free tier. Acceptable trade-off.
- **Embedding cost** — one embedding call per query plus one per invoice at ingest. Negligible at this scale.
- **No SQL exposure** — the LLM never sees a schema or writes queries; retrieval is handled by the search engine.
- **Multi-turn history** — the agent keeps the last 6 turns and injects them into the prompt, so follow-up questions ("what about in USD?") resolve correctly.
