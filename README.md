# Invoice Data Extractor + Conversational Agent

Three-step pipeline: **extract → store → chat**.

1. `extractor.py` — pulls structured data from invoice PDFs/images using GPT-4o
2. `store.py` — loads the extracted CSV into a local SQLite database
3. `app.py` — Streamlit browser UI to query the data in plain English

---

## How the extractor works

| File type | Detection | Strategy |
|---|---|---|
| Text-based PDF | ≥ 200 chars extractable | `pdfplumber` → GPT-4o text prompt |
| Scanned PDF | < 200 chars extractable | `pdf2image` → GPT-4o Vision |
| Image file (PNG, JPG, …) | file extension | GPT-4o Vision directly |

The script auto-detects which path to use — you just point it at a folder.

---

## Setup

### 1. System dependency (for scanned PDF support)

**macOS**
```bash
brew install poppler
```

**Ubuntu / Debian**
```bash
sudo apt-get install poppler-utils
```

**Windows**  
Download from https://github.com/oschwartz10612/poppler-windows/releases and add the `bin/` folder to your PATH.

### 2. Python dependencies

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

### 3. API provider — choose one

**Option A: Standard OpenAI**
```bash
export OPENAI_API_KEY=sk-...                         # macOS / Linux
set OPENAI_API_KEY=sk-...                            # Windows CMD
$env:OPENAI_API_KEY="sk-..."                         # Windows PowerShell
```

**Option B: Azure AI Foundry (Azure OpenAI Service)**
```bash
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_API_KEY=your-azure-key
export AZURE_OPENAI_DEPLOYMENT=gpt-4o        # your deployment name in Foundry
export AZURE_OPENAI_API_VERSION=2024-12-01-preview   # optional, this is the default
```

The script auto-detects which provider to use. `AZURE_OPENAI_ENDPOINT` takes priority if set.

---

## Usage

### Step 1 — Extract invoice data
```bash
python extractor.py ./invoices
python extractor.py ./invoices --output my_results.csv   # custom output name
```

### Step 2 — Load into database
```bash
python store.py extracted_invoices.csv
python store.py my_results.csv --db invoices.db          # custom DB name
```

### Step 3 — Launch the chat UI
```bash
streamlit run app.py
streamlit run app.py -- --db invoices.db                 # custom DB name
```

Then open http://localhost:8501 in your browser.

### Example output (console)

```
Found 5 invoice file(s) in 'invoices'. Starting extraction...

  [01/05] invoice_001.pdf  →  ✓  (text+gpt4o)   | #INV-2024-001 | Acme Corp | 1250.00 EUR
  [02/05] invoice_002.pdf  →  ✓  (vision+gpt4o)  | #2024/55      | Beta Ltd  | 890.50 USD
  [03/05] scan_march.pdf   →  ✓  (vision+gpt4o)  | #M-0033       | Gamma GmbH| 3400.00 EUR
  [04/05] receipt.png      →  ✓  (vision+gpt4o)  | #RC-99        | Delta Inc | 45.00 GBP
  [05/05] broken.pdf       →  ✗  ERROR: ...

────────────────────────────────────────────────────
✓  Extraction complete.  Results written to: extracted_invoices.csv
   Total files : 5
   Successful  : 4
   Errors      : 1
────────────────────────────────────────────────────
```

---

## Output CSV columns

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

## Design decisions

- **One pipeline for both levels**: complexity is auto-detected at runtime rather than requiring the user to pre-sort files. This makes the solution more practical in real-world use.
- **GPT-4o for both paths**: avoids maintaining two separate ML stacks. The same model handles text understanding (Level 2) and OCR + understanding (Level 3 vision).
- **`response_format: json_object`**: forces the model to return valid JSON — eliminates the need for fragile post-processing or regex cleanup.
- **`temperature=0`**: deterministic outputs for better repeatability across runs.
- **`detail: high` for vision**: ensures GPT-4o reads fine print, small fonts, and dense table data accurately.
- **`MAX_VISION_PAGES = 4`**: caps API cost on multi-page documents while covering virtually all real invoices.
