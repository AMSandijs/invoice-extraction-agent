# Invoice Data Extraction & RAG Agent

Upload invoice documents and chat with your data in plain English. GPT-4o extracts structured fields from any invoice format (text PDF, scanned PDF, image); a hybrid search index makes every field queryable by natural language.

**Live demo:** [https://ca-invoice-rag.yellowriver-3ff2a4c5.swedencentral.azurecontainerapps.io](https://ca-invoice-rag.yellowriver-3ff2a4c5.swedencentral.azurecontainerapps.io)

> First visit may take ~20 seconds to wake up (scale-to-zero).

---

## Invoice flow

```mermaid
flowchart TD
    subgraph Ingest["📥 Ingest path"]
        A([User uploads invoice]) --> B[Streamlit\nUpload screen]
        B -->|uploader.py| C[(Blob Storage\ninvoices/ container)]
        C -->|blob trigger| D[Azure Function\nprocess_invoice]
        D -->|text PDF| E[pdfplumber\ntext extract]
        D -->|scanned PDF\nor image| F[PyMuPDF\nrender to PNG]
        E --> G[GPT-4o\nextract structured fields]
        F --> G
        G -->|JSON record| H[(Cosmos DB\nrecords container)]
        H -->|text-embedding-3-large| I[(AI Search\nhybrid index)]
    end

    subgraph Query["💬 Query path"]
        J([User asks a question]) --> K[Streamlit\nChat screen]
        K -->|agent.py\nhybrid search| I
        I -->|top matching invoices| L[GPT-4o\nRAG answer]
        L --> K
    end
```

---

## Tech stack

| Layer | Technology |
|---|---|
| **LLM** | Azure OpenAI — GPT-4o (extraction + chat) |
| **Embeddings** | Azure OpenAI — `text-embedding-3-large` (3 072 dims) |
| **Search** | Azure AI Search — hybrid keyword + vector index |
| **Database** | Azure Cosmos DB — structured invoice records |
| **File storage** | Azure Blob Storage — raw invoice files |
| **Serverless** | Azure Functions (Python v2, consumption plan) |
| **Infrastructure** | OpenTofu (Terraform-compatible) |
| **Frontend** | Streamlit — upload screen, chat screen, admin panel |
| **Auth** | `DefaultAzureCredential` — no secrets stored anywhere |
| **PDF (text)** | pdfplumber |
| **PDF (vision)** | PyMuPDF (fitz) |
| **Images** | Pillow |
| **Runtime** | Python 3.10+ |

### Python dependencies

```
# Core
openai                   GPT-4o API + embeddings
streamlit                browser UI
pdfplumber               text extraction from text-based PDFs
PyMuPDF (fitz)           rendering scanned PDFs to images
Pillow                   image normalisation
python-dotenv            load .env config

# Azure SDK
azure-identity           DefaultAzureCredential / AAD auth
azure-storage-blob       direct blob upload from the UI
azure-cosmos             Cosmos DB client (sync + rebuild)
azure-search-documents   hybrid search + index management
```

---

## Repository layout

```
invoice-agent/
├── app.py                  Home screen — launch pad + admin panel
├── pages/
│   ├── 1_Upload.py         Upload invoices, poll for results, download CSV
│   └── 2_Chat.py           Chat with the RAG agent
├── agent.py                RAG agent — AI Search retrieval + GPT-4o
├── uploader.py             Upload a file to Azure Blob Storage
├── sync.py                 Admin ops — rebuild index, clear all, export CSV
├── extractor.py            Standalone local extraction pipeline (no cloud needed)
├── function_app/
│   ├── function_app.py     Azure Function entry points (blob trigger + change feed)
│   ├── extraction.py       GPT-4o extraction logic (text + vision)
│   ├── cosmos_writer.py    Cosmos DB upsert / soft-delete helpers
│   ├── search_indexer.py   AI Search index management + document push
│   └── requirements.txt    Function App dependencies (deployed with the function)
├── infra/                  OpenTofu — all Azure resources
├── docs/adr/               Architecture Decision Records
├── scripts/
│   └── rebuild_search_index.py   CLI wrapper for sync.rebuild()
├── tests/                  Unit tests — RAG agent
├── Dockerfile              Container image for the Streamlit app
├── deploy.sh               One-command deploy to Azure Container Apps
├── requirements.txt        App dependencies
├── requirements-dev.txt    + pytest
└── .env.sample             Copy to .env and fill in endpoints
```

---

## Using the app

### Home screen

The home screen shows how many invoices are currently indexed and gives you two entry points.

- **Upload Invoices** — go to the upload screen to add new invoices
- **Chat with Agent** — go to the chat screen to ask questions about indexed invoices
- **⚙ Admin** (expandable panel at the bottom):
  - **Sync index from Cosmos DB** — if the invoice count looks wrong, use this to rebuild the AI Search index from the source of truth in Cosmos DB
  - **Export CSV** — download all stored invoices as a CSV file with all extracted fields
  - **Clear all invoices** — permanently deletes everything from Cosmos DB and resets the Search index (requires a confirmation checkbox)

### Upload screen

1. Click **Browse files** and select one or more invoice files (PDF, PNG, JPG)
2. Click **Upload and process**
3. Each file uploads to Azure Blob Storage, which triggers the Azure Function to extract structured data using GPT-4o
4. The screen polls every few seconds and shows a live status for each file — a green tick when extraction is complete, with the supplier name, invoice number, and total
5. Once all files are processed, you can **Download CSV** with the extracted data or go straight to **Chat now →**

Uploading the same file again re-extracts it and overwrites the existing record — no duplicates are created.

### Chat screen

Type any question about your invoices in the message box and press Enter or click **Send**.

Example questions:
- *"What invoices do I have?"*
- *"What is the total amount across all invoices?"*
- *"Which supplier has the highest invoice?"*
- *"Show me all invoices in USD"*
- *"What is the tax amount on the Glass Act invoice?"*

The agent retrieves the most relevant invoice records from AI Search and passes them to GPT-4o to generate an answer. It keeps track of the last few turns so follow-up questions work naturally.

**Clear conversation** — resets the chat history without affecting the indexed invoices.

---

## Setup

### Prerequisites

| Tool | macOS | Windows |
|---|---|---|
| [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli) | `brew install azure-cli` | `winget install Microsoft.AzureCLI` |
| [OpenTofu](https://opentofu.org/docs/intro/install/) | `brew install opentofu` | `winget install OpenTofu.OpenTofu` |
| [Azure Functions Core Tools](https://docs.microsoft.com/azure/azure-functions/functions-run-local) | `brew tap azure/functions && brew install azure-functions-core-tools@4` | `winget install Microsoft.AzureFunctionsCoreTools` |
| [Python 3.10+](https://www.python.org/downloads/) | `brew install python` | `winget install Python.Python.3.11` |

---

### Deploy to Azure (one command)

```bash
az login
cd infra && tofu init   # first time only
cd ..
./deploy.sh
```

> **Windows:** run in Git Bash or WSL. `deploy.sh` uses bash.

`deploy.sh` provisions all Azure infrastructure, builds the Docker image in ACR, and deploys to Container Apps. Takes ~5 minutes total.

#### What gets created

Resource Group, Storage Account, Azure OpenAI (GPT-4o + embeddings), Cosmos DB, AI Search, Function App, Container Registry, Container Apps. All resource-to-resource calls use managed identity — no keys stored anywhere.

---

### Deploy the Azure Function

```bash
cd function_app
func azure functionapp publish <function_app_name> --python
```

Replace `<function_app_name>` with the value from `tofu output function_app_name`.

---

### Run locally

**1. Configure environment**

macOS / Linux:
```bash
cp .env.sample .env
```

Windows (Command Prompt):
```cmd
copy .env.sample .env
```

Fill in `.env` with values from `tofu -chdir=infra output`:

```env
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_GPT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
STORAGE_ACCOUNT_NAME=...
COSMOS_ENDPOINT=https://...
COSMOS_DATABASE=invoices
COSMOS_CONTAINER=records
SEARCH_ENDPOINT=https://...
SEARCH_INDEX=invoices-idx
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Authenticate and run**

```bash
az login
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

**macOS launcher** — right-click `launch.command` → Open (first time only), then double-click to start.

---

### App screens

| Screen | What it does |
|---|---|
| **Home** | Launch pad + invoice count + admin panel (sync, export CSV, clear all) |
| **Upload Invoices** | Select PDFs or images, upload to Azure, watch extraction results live, download CSV |
| **Chat with Agent** | Ask questions about indexed invoices in plain English |

---

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/                   # RAG agent unit tests
pytest function_app/tests/      # Function App ingestion tests
```

---

## Design decisions

**Extraction**

- **Auto-detected strategy** — text PDF, scanned PDF, and image are detected at runtime so the user doesn't need to pre-sort files.
- **GPT-4o for every path** — one model handles both text understanding and OCR + vision, avoiding two separate ML stacks.
- **`response_format: json_object`** — forces valid JSON output; no fragile regex cleanup.
- **`temperature=0`** — deterministic, repeatable extraction.
- **`MAX_VISION_PAGES = 4`** — caps Vision API cost on multi-page documents.

**RAG agent**

- **Hybrid retrieval** — keyword + vector search so vague questions still find the right records.
- **Top-k = 50** — retrieves enough records for GPT-4o to compute aggregates (totals, averages, rankings) in-prompt at demo scale.
- **Managed identity / Entra ID auth** — no secrets stored; access is controlled through Azure RBAC and scales to a hosted deployment without code changes.
- **Cosmos DB Change Feed** — Azure Function listens for changes and keeps the AI Search index in sync automatically (soft-deletes propagate to Search).
