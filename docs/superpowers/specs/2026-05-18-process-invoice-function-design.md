# Design — `process_invoice` Ingestion Function

**Date:** 2026-05-18
**Phase:** 2 (Azure-native backend)
**Scope:** The blob-triggered ingestion Function only. The `agent.py` rewrite for
AI Search retrieval and the Streamlit update are a separate, later work block.

---

## 1. Purpose

Replace the Phase 1 manual CLI steps (`extractor.py` → `store.py`) with a single
Azure Function that runs automatically whenever an invoice file is uploaded to Blob
Storage. The Function extracts structured data with GPT-4o, stores it in Cosmos DB,
and pushes it into an Azure AI Search index for later retrieval by the RAG agent.

**Success criteria:** uploading a file to the `invoices/` blob container results in
— with no manual step — a structured record in Cosmos DB and a searchable, vector-
embedded document in the `invoices-idx` Search index.

---

## 2. Target infrastructure (already deployed)

All resources live in `rg-invoice-rag`, Sweden Central, subscription
`21a1faed-77bc-4545-a743-eda9becaebc6` (name suffix `infim0`):

| Role | Resource |
|------|----------|
| Upload container | `stinvoiceraginfim0` / blob container `invoices` |
| Compute | `func-invoice-rag-infim0` (Linux Consumption, Python 3.11) |
| LLM | `aoai-invoice-rag-infim0` — deployments `gpt-4o`, `text-embedding-3-large` |
| Records store | `cosmos-invoice-rag-infim0` — db `invoices`, container `records` (PK `/supplier_name`) |
| Search | `srch-invoice-rag-infim0` — index `invoices-idx` (created by the Function) |

The Function App's system-assigned managed identity already holds the required RBAC
roles (Storage Blob Data Contributor, Cognitive Services OpenAI User, Search Index
Data Contributor, Search Service Contributor, Cosmos DB Built-in Data Contributor).
Endpoints are already wired into the Function App settings by Terraform.

---

## 3. Repository layout

A self-contained Azure Functions app in a new `function_app/` directory. Phase 1
scripts (`extractor.py`, `store.py`, `agent.py`, `app.py`) are left untouched.

```
function_app/
  function_app.py      # blob trigger entrypoint (Python v2 programming model)
  extraction.py        # GPT-4o extraction — ported from extractor.py, PyMuPDF instead of pdf2image
  cosmos_writer.py     # upsert an invoice record into Cosmos
  search_indexer.py    # ensure index exists, embed text, push document
  host.json            # Functions host config
  requirements.txt     # Function-only dependencies
  .funcignore          # exclude local cruft from the deployment package
```

---

## 4. Key technical decision — PDF rendering

Phase 1's `extractor.py` renders scanned PDFs to images with `pdf2image`, which
depends on the **`poppler` system binary**. The Linux Consumption plan does not
allow installing apt packages, so `pdf2image` cannot be used in the Function.

**Decision:** use **PyMuPDF (`pymupdf`)** to render PDF pages to images. It is a
pure-Python wheel with no system dependency and installs cleanly on Functions.

Unchanged from Phase 1: text extraction via `pdfplumber`, the GPT-4o text and vision
calls, and the extraction `SYSTEM_PROMPT` (reused verbatim).

| File type | Detection | Strategy |
|-----------|-----------|----------|
| Text-based PDF | ≥ 200 extractable chars (`pdfplumber`) | text → GPT-4o |
| Scanned PDF | < 200 extractable chars | **PyMuPDF** → image → GPT-4o Vision |
| Image file | extension | GPT-4o Vision directly |

`MAX_VISION_PAGES = 4` and `TEXT_PDF_MIN_CHARS = 200` are carried over from Phase 1.

---

## 5. Processing flow

```
new blob in `invoices/` container
  → process_invoice (blob trigger, connection = AzureWebJobsStorage)
  → read blob bytes
  → detect type → extract with GPT-4o → structured JSON
  → build invoice record (Section 6)
  → upsert to Cosmos container `records`
  → on success: embed text summary → push document to Search index `invoices-idx`
  → on extraction failure: write error record to Cosmos, skip Search push
```

The trigger binds to `invoices/{name}` on the `AzureWebJobsStorage` connection
(the same storage account, already configured).

---

## 6. Data model

### 6.1 Cosmos DB document (`records` container)

The 15 Phase 1 fields plus operational fields:

| Field | Source | Notes |
|-------|--------|-------|
| `id` | `sha1(blob_name)` | deterministic — re-upload upserts cleanly |
| `blob_name` | trigger | source filename |
| `supplier_name` | extraction | **partition key**; `"unknown"` if null |
| `method` | extraction | `text+gpt4o` / `vision+gpt4o` |
| `invoice_number`, `invoice_date`, `buyer_name`, `total_amount`, `currency`, `subtotal`, `tax_amount`, `tax_rate`, `due_date`, `po_number`, `payment_terms`, `line_items` | extraction | Phase 1 fields; `line_items` stored as a native JSON array |
| `processed_at` | Function | ISO 8601 UTC timestamp |
| `status` | Function | `extracted` or `error` |
| `error` | Function | message when `status = error`, else null |

### 6.2 AI Search index `invoices-idx`

| Field | Type | Attributes |
|-------|------|-----------|
| `id` | Edm.String | key |
| `supplier_name`, `buyer_name`, `currency`, `invoice_number`, `po_number` | Edm.String | searchable, filterable |
| `invoice_date`, `due_date` | Edm.String | filterable, sortable |
| `total_amount`, `subtotal`, `tax_amount` | Edm.Double | filterable, sortable |
| `blob_name` | Edm.String | retrievable |
| `content` | Edm.String | searchable — a plain-text summary of the invoice |
| `content_vector` | Collection(Edm.Single) | 3072 dims, HNSW profile — hybrid retrieval |

`content` is a synthesized one-paragraph summary of the invoice (supplier, buyer,
number, date, amounts, line-item descriptions). It is the text that gets embedded
into `content_vector` via `text-embedding-3-large` (3072 dimensions).

Only records with `status = extracted` are pushed to Search; error records stay in
Cosmos only.

---

## 7. Authentication

No keys or connection strings for resource access. All SDK clients authenticate with
`DefaultAzureCredential`, resolving to the Function App's managed identity at runtime:

- **Azure OpenAI** — `AzureOpenAI` client with an `azure_ad_token_provider` built from
  `DefaultAzureCredential` (scope `https://cognitiveservices.azure.com/.default`).
- **Cosmos DB** — `CosmosClient(url, credential=DefaultAzureCredential())`.
- **AI Search** — `SearchClient` / `SearchIndexClient` with `DefaultAzureCredential`.

The blob trigger itself uses the `AzureWebJobsStorage` connection (already set).

Configuration is read from Function App settings (already populated by Terraform):
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_GPT_DEPLOYMENT`,
`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`, `COSMOS_ENDPOINT`,
`COSMOS_DATABASE`, `COSMOS_CONTAINER`, `SEARCH_ENDPOINT`, `SEARCH_INDEX`.

---

## 8. Index creation

The Function **ensures the Search index exists** on cold start: `search_indexer.py`
calls `SearchIndexClient.create_or_update_index` with the Section 6.2 schema. This is
idempotent and removes the need for a separate setup script or for Terraform to manage
Search index schemas (which `azurerm` does not model well).

---

## 9. Error handling

| Situation | Behaviour |
|-----------|-----------|
| Extraction fails (corrupt file, bad JSON, GPT-4o error) | Catch it; write a Cosmos record with `status="error"` and the message; **skip** the Search push. One bad invoice never crashes the run. Mirrors Phase 1's CSV `error` column. |
| Unsupported file extension | Same as above — error record, no Search push. |
| Transient infra error (Cosmos/Search/OpenAI throttling or outage) | Let the exception propagate → Azure Functions retries the blob → poison blob after retries exhausted. |
| Re-upload of an existing filename | Deterministic `id = sha1(blob_name)` → upsert in both Cosmos and Search; no duplicates. |

All processing steps log to Application Insights (already connected) via the standard
`logging` module.

---

## 10. Out of scope

- `agent.py` rewrite for AI Search retrieval — next work block.
- `app.py` / Streamlit changes — next work block.
- Semantic ranker — requires AI Search Basic tier; the Free tier does keyword + vector
  hybrid only.
- Document Intelligence — deliberately excluded; GPT-4o Vision covers scanned PDFs.
- CI/CD for Function deployment — Phase 4.

---

## 11. Verification

After `func azure functionapp publish func-invoice-rag-infim0`:

1. Upload a known text-based PDF invoice to the `invoices` container.
2. Confirm a `status="extracted"` document appears in the Cosmos `records` container
   with correct fields.
3. Confirm a matching document exists in the `invoices-idx` Search index, with a
   populated `content_vector`.
4. Upload a scanned/image invoice — confirm the PyMuPDF vision path produces a record.
5. Upload a deliberately broken file — confirm a `status="error"` record in Cosmos and
   no Search document.
