# Invoice Data Extraction & RAG Agent

Home-assignment solution:

- **Mandatory part** — extract structured data from invoice documents.
- **Optional Part, Option 2** — a conversational RAG agent that answers questions
  about the extracted invoices in plain English.

It can run two ways:

| | Local pipeline (Phase 1) | Azure backend + RAG agent (Phase 2) |
|---|---|---|
| Extraction | `extractor.py` over a local folder → CSV | Blob upload → Azure Function (GPT-4o) |
| Storage | CSV file | Azure Cosmos DB |
| Query | — | Azure AI Search + GPT-4o, via a Streamlit chat agent |
| Cloud setup | OpenAI API key only | OpenTofu-provisioned Azure resources, managed-identity auth |

The local pipeline is the quickest way to run just the mandatory extraction.
The Azure backend is the full Option 2 solution: upload an invoice and chat with it.

---

## Repository layout

| Path | Purpose |
|---|---|
| `extractor.py` | Local extractor — invoice files → structured CSV (Phase 1) |
| `store.py` | Legacy Phase 1 CSV→SQLite loader. Retained for reference; not used by the RAG agent. |
| `agent.py` | RAG agent — hybrid retrieval over Azure AI Search + GPT-4o |
| `app.py` | Streamlit chat UI for the RAG agent |
| `function_app/` | Azure Function `process_invoice` — blob-triggered ingestion |
| `infra/` | OpenTofu/Terraform for all Azure resources |
| `tests/` | Unit tests for the RAG agent |
| `docs/superpowers/` | Design specs and implementation plans |

---

## Part 1 — Local extraction (mandatory part)

`extractor.py` pulls structured data from a folder of invoice PDFs/images using
GPT-4o and writes a CSV. No Azure infrastructure required — just an OpenAI (or
Azure OpenAI) API key.

### How it works

| File type | Detection | Strategy |
|---|---|---|
| Text-based PDF | ≥ 200 chars extractable | `pdfplumber` → GPT-4o text prompt |
| Scanned PDF | < 200 chars extractable | `pdf2image` → GPT-4o Vision |
| Image file (PNG, JPG, …) | file extension | GPT-4o Vision directly |

The script auto-detects which path to use — point it at a folder.

### Setup

**1. System dependency** (only for the scanned-PDF path)

```bash
brew install poppler                 # macOS
sudo apt-get install poppler-utils   # Ubuntu / Debian
```
Windows: download from https://github.com/oschwartz10612/poppler-windows/releases
and add the `bin/` folder to your PATH.

**2. Python dependencies** (Python 3.10+)

```bash
pip install -r requirements.txt
```

**3. API provider** — set one:

```bash
# Standard OpenAI
export OPENAI_API_KEY=sk-...

# OR Azure OpenAI (takes priority if set)
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_API_KEY=your-azure-key
export AZURE_OPENAI_DEPLOYMENT=gpt-4o
export AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

### Usage

```bash
python extractor.py ./invoices
python extractor.py ./invoices --output my_results.csv   # custom output name
```

### Output CSV columns

| Column | Description |
|---|---|
| `file` | Source filename |
| `method` | Extraction strategy used |
| `invoice_number` | Invoice reference number |
| `invoice_date` | Date issued (ISO 8601 where possible) |
| `supplier_name` | Issuing company/person |
| `buyer_name` | Billed party |
| `total_amount` | Final payable amount (float) |
| `currency` | ISO 3-letter code or symbol |
| `subtotal` | Amount before tax |
| `tax_amount` | Tax total |
| `tax_rate` | Tax percentage |
| `due_date` | Payment due date |
| `po_number` | Purchase order number |
| `payment_terms` | e.g. "Net 30" |
| `line_items` | JSON array of line items |
| `error` | Error message if extraction failed |

---

## Part 2 — Azure backend + RAG agent (Optional Part, Option 2)

Invoices uploaded to Blob Storage are processed automatically and become
queryable through a chat agent.

### Architecture

```
Blob Storage (invoices container)
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

### Deploy the infrastructure

```bash
cd infra
tofu init
tofu plan
tofu apply
```

This provisions the resource group, Storage, Function App, Azure OpenAI
(GPT-4o + `text-embedding-3-large`), Cosmos DB, and AI Search. Endpoints are
exposed via `tofu output`.

### Deploy the Function

```bash
cd function_app
func azure functionapp publish <function_app_name>   # name from `tofu output`
```

Uploading an invoice to the `invoices` blob container then triggers extraction
end-to-end into Cosmos DB and the AI Search index.

### Run the app

```bash
cp .env.sample .env          # fill in endpoints from `cd infra && tofu output`
az login
pip install -r requirements.txt
```

**Option A — double-click launcher (macOS)**

Right-click `launch.command` → Open (first time only, to clear Gatekeeper). After that, double-click it any time — the browser opens automatically.

**Option B — terminal**

```bash
streamlit run app.py
```

Open http://localhost:8501.

The app has two modes:
- **Upload Invoices** — select PDFs, upload to Azure, see extracted data, download a CSV
- **Chat with Agent** — ask questions in plain English about indexed invoices

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/                  # RAG agent
pytest function_app/tests/     # ingestion Function (needs function_app deps)
```

---

## Design decisions

**Extraction**

- **One pipeline, auto-detected complexity** — text PDF, scanned PDF, and image
  are detected at runtime rather than requiring the user to pre-sort files.
- **GPT-4o for every path** — one model handles both text understanding and
  OCR + understanding, avoiding two separate ML stacks.
- **`response_format: json_object`** — forces valid JSON, no fragile regex cleanup.
- **`temperature=0`** — deterministic, repeatable extraction.
- **`MAX_VISION_PAGES = 4`** — caps API cost on multi-page documents.

**RAG agent**

- **Hybrid retrieval** — keyword + vector search over an invoice-summary index,
  so vague questions still find the right records.
- **Big top-k** — retrieves up to 50 records so GPT-4o can compute aggregate
  answers (totals, averages, "which is highest") in-prompt at demo scale.
- **Managed identity / Entra ID auth** — no keys stored; per-user access is
  granted through Azure RBAC and scales to a hosted deployment without code changes.
