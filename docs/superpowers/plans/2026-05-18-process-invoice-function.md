# process_invoice Ingestion Function — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a blob-triggered Azure Function that extracts invoice data with GPT-4o, writes records to Cosmos DB, and pushes embedded documents to Azure AI Search.

**Architecture:** A self-contained Azure Functions app (Python v2 model) in a new `function_app/` directory. A blob trigger on the `invoices/` container fans out to three focused modules: `extraction.py` (GPT-4o, PyMuPDF for PDF rendering), `cosmos_writer.py` (record assembly + upsert), `search_indexer.py` (index schema, embedding, push). Pure logic is unit-tested with mocked Azure SDKs; the I/O glue is verified by a manual end-to-end test against the deployed resources.

**Tech Stack:** Python 3.11, Azure Functions, `azure-functions`, `azure-identity`, `azure-cosmos`, `azure-search-documents`, `openai` (AzureOpenAI), `pymupdf`, `pdfplumber`, `pillow`, `pytest`.

**Reference spec:** `docs/superpowers/specs/2026-05-18-process-invoice-function-design.md`

---

## File Structure

```
function_app/
  function_app.py        # blob trigger entrypoint + orchestration
  extraction.py          # file-type detection + GPT-4o extraction
  cosmos_writer.py        # record assembly + Cosmos upsert
  search_indexer.py       # index schema, content summary, embedding, push
  host.json               # Functions host config
  requirements.txt        # runtime dependencies (deployed)
  requirements-dev.txt    # test-only dependencies
  .funcignore             # files excluded from the deployment package
  local.settings.json.sample  # template for local settings (not deployed)
  conftest.py             # pytest path setup + shared fixtures
  tests/
    test_extraction.py
    test_cosmos_writer.py
    test_search_indexer.py
    test_function_app.py
```

Each module has one responsibility and a small interface. Phase 1 scripts
(`extractor.py`, `store.py`, `agent.py`, `app.py`) are not touched.

---

## Task 1: Scaffold the Function app

**Files:**
- Create: `function_app/host.json`
- Create: `function_app/requirements.txt`
- Create: `function_app/requirements-dev.txt`
- Create: `function_app/.funcignore`
- Create: `function_app/local.settings.json.sample`
- Create: `function_app/conftest.py`

- [ ] **Step 1: Create `function_app/host.json`**

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": { "isEnabled": true, "excludedTypes": "Request" }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

- [ ] **Step 2: Create `function_app/requirements.txt`**

```
azure-functions
azure-identity
azure-cosmos
azure-search-documents
openai
pymupdf
pdfplumber
pillow
```

- [ ] **Step 3: Create `function_app/requirements-dev.txt`**

```
-r requirements.txt
pytest
```

- [ ] **Step 4: Create `function_app/.funcignore`**

```
.git*
.venv/
venv/
tests/
conftest.py
__pycache__/
.pytest_cache/
requirements-dev.txt
local.settings.json
local.settings.json.sample
```

- [ ] **Step 5: Create `function_app/local.settings.json.sample`**

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "<storage-connection-string>",
    "AZURE_OPENAI_ENDPOINT": "https://aoai-invoice-rag-infim0.openai.azure.com/",
    "AZURE_OPENAI_GPT_DEPLOYMENT": "gpt-4o",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",
    "AZURE_OPENAI_API_VERSION": "2024-12-01-preview",
    "COSMOS_ENDPOINT": "https://cosmos-invoice-rag-infim0.documents.azure.com:443/",
    "COSMOS_DATABASE": "invoices",
    "COSMOS_CONTAINER": "records",
    "SEARCH_ENDPOINT": "https://srch-invoice-rag-infim0.search.windows.net",
    "SEARCH_INDEX": "invoices-idx"
  }
}
```

- [ ] **Step 6: Create `function_app/conftest.py`**

The presence of this file at the `function_app/` root puts that directory on
`sys.path`, so tests can `import extraction` etc. It also holds shared fixtures.

```python
"""Pytest configuration and shared fixtures for the Function app tests."""

import io
from unittest.mock import MagicMock

import fitz  # PyMuPDF
import pytest
from PIL import Image


@pytest.fixture
def png_bytes():
    """A minimal valid PNG image as bytes."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def text_pdf_bytes():
    """A PDF carrying enough machine-readable text to count as text-based."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Invoice number INV-001 supplier Acme Corp. " * 8)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def blank_pdf_bytes():
    """A PDF with a page but no extractable text — stands in for a scan."""
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def make_chat_client():
    """Factory: a fake OpenAI client whose chat completion returns json_content."""
    def _make(json_content):
        client = MagicMock()
        choice = MagicMock()
        choice.message = MagicMock(content=json_content)
        client.chat.completions.create.return_value.choices = [choice]
        return client
    return _make
```

- [ ] **Step 7: Commit**

```bash
git add function_app/host.json function_app/requirements.txt \
  function_app/requirements-dev.txt function_app/.funcignore \
  function_app/local.settings.json.sample function_app/conftest.py
git commit -m "Scaffold process_invoice Function app"
```

---

## Task 2: File-type detection and PDF/image helpers

**Files:**
- Create: `function_app/extraction.py`
- Test: `function_app/tests/test_extraction.py`

- [ ] **Step 1: Write the failing test**

Create `function_app/tests/test_extraction.py`:

```python
import extraction


def test_detect_strategy_image_extensions():
    assert extraction.detect_strategy("scan.png", b"") == "vision-image"
    assert extraction.detect_strategy("photo.JPG", b"") == "vision-image"


def test_detect_strategy_unsupported():
    assert extraction.detect_strategy("notes.txt", b"") == "unsupported"
    assert extraction.detect_strategy("noextension", b"") == "unsupported"


def test_detect_strategy_text_pdf(text_pdf_bytes):
    assert extraction.detect_strategy("invoice.pdf", text_pdf_bytes) == "text"


def test_detect_strategy_scanned_pdf(blank_pdf_bytes):
    assert extraction.detect_strategy("scan.pdf", blank_pdf_bytes) == "vision-pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'extraction'`

- [ ] **Step 3: Write minimal implementation**

Create `function_app/extraction.py`:

```python
"""GPT-4o invoice extraction for the Azure Function.

Ported from extractor.py. Uses PyMuPDF to render scanned PDFs to images so the
Function needs no system binaries (pdf2image's poppler dependency is dropped).
"""

import io
import base64

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

# A PDF with at least this many extractable characters is treated as text-based.
TEXT_PDF_MIN_CHARS = 200

# Cap the number of PDF pages sent to the vision model (cost control).
MAX_VISION_PAGES = 4

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def _suffix(blob_name: str) -> str:
    """Return the lowercased file extension including the dot, or ''."""
    return "." + blob_name.rsplit(".", 1)[-1].lower() if "." in blob_name else ""


def _pdf_text(data: bytes) -> str:
    """Extract all machine-readable text from a PDF."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        parts = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(parts).strip()


def _pdf_has_text(data: bytes) -> bool:
    """True if the PDF has enough extractable text to skip OCR."""
    try:
        return len(_pdf_text(data)) >= TEXT_PDF_MIN_CHARS
    except Exception:
        return False


def _pdf_to_png_pages(data: bytes) -> list[bytes]:
    """Render the first MAX_VISION_PAGES PDF pages to PNG bytes via PyMuPDF."""
    pages: list[bytes] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page in list(doc)[:MAX_VISION_PAGES]:
            pages.append(page.get_pixmap(dpi=200).tobytes("png"))
    finally:
        doc.close()
    return pages


def _image_to_png(data: bytes) -> bytes:
    """Normalise any image to RGB PNG bytes."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def detect_strategy(blob_name: str, data: bytes) -> str:
    """Return the extraction strategy for a file.

    One of: 'text', 'vision-pdf', 'vision-image', 'unsupported'.
    """
    suffix = _suffix(blob_name)
    if suffix == ".pdf":
        return "text" if _pdf_has_text(data) else "vision-pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "vision-image"
    return "unsupported"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_extraction.py -v`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app/extraction.py function_app/tests/test_extraction.py
git commit -m "Add file-type detection and PDF/image helpers"
```

---

## Task 3: GPT-4o extraction

**Files:**
- Modify: `function_app/extraction.py`
- Test: `function_app/tests/test_extraction.py`

- [ ] **Step 1: Write the failing test**

Append to `function_app/tests/test_extraction.py`:

```python
import pytest

_VALID_JSON = '{"invoice_number": "INV-001", "supplier_name": "Acme Corp", "total_amount": 1250.0, "currency": "EUR"}'


def test_extract_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extraction.extract(MagicMock(), "gpt-4o", "notes.txt", b"")


def test_extract_image_path(make_chat_client, png_bytes):
    client = make_chat_client(_VALID_JSON)
    data, method = extraction.extract(client, "gpt-4o", "receipt.png", png_bytes)
    assert data["invoice_number"] == "INV-001"
    assert method == "vision+gpt4o"
    client.chat.completions.create.assert_called_once()


def test_extract_text_pdf_path(make_chat_client, text_pdf_bytes):
    client = make_chat_client(_VALID_JSON)
    data, method = extraction.extract(client, "gpt-4o", "invoice.pdf", text_pdf_bytes)
    assert data["supplier_name"] == "Acme Corp"
    assert method == "text+gpt4o"
```

Add `from unittest.mock import MagicMock` to the imports at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_extraction.py -v`
Expected: FAIL — `AttributeError: module 'extraction' has no attribute 'extract'`

- [ ] **Step 3: Write minimal implementation**

Append to `function_app/extraction.py`:

```python
import json

# Extraction prompt — carried over verbatim from extractor.py (Phase 1).
SYSTEM_PROMPT = """You are a precise invoice data extraction assistant.
Extract the following fields from the invoice and return ONLY a valid JSON object — no markdown, no explanation.

Required fields:
  invoice_number   - The invoice identifier/reference number (string)
  invoice_date     - Date the invoice was issued (ISO 8601 if possible, e.g. "2024-03-15")
  supplier_name    - Name of the company or person issuing the invoice (string)
  total_amount     - Final total payable amount as a number (float, no currency symbol)
  currency         - 3-letter ISO currency code if determinable (e.g. "EUR", "USD"), else the symbol

Optional fields (include if present, otherwise use null):
  buyer_name       - Name of the customer / billed party
  due_date         - Payment due date (ISO 8601)
  subtotal         - Amount before tax (float)
  tax_amount       - Total tax amount (float)
  tax_rate         - Tax percentage as a string (e.g. "21%")
  po_number        - Purchase order number
  payment_terms    - Payment terms (e.g. "Net 30")
  line_items       - Array of line items, each: {"description": str, "quantity": num, "unit_price": num, "total": num}

Rules:
  - Return ONLY the JSON object. No prose.
  - Use null for any field that cannot be found or inferred.
  - Numbers must be plain floats (e.g. 1234.56), never strings with symbols.
"""


def _chat_extract_text(client, deployment: str, text: str) -> dict:
    """Send invoice text to GPT-4o and parse the structured JSON reply."""
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract invoice data from the following text.\n\n"
                    f"--- INVOICE TEXT START ---\n{text}\n--- INVOICE TEXT END ---"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def _chat_extract_images(client, deployment: str, png_pages: list[bytes]) -> dict:
    """Send page images to GPT-4o Vision and parse the structured JSON reply."""
    content = [{"type": "text", "text": "Extract all invoice data from the image(s) below."}]
    for png in png_pages:
        b64 = base64.b64encode(png).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            }
        )
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def extract(client, deployment: str, blob_name: str, data: bytes) -> tuple[dict, str]:
    """Extract invoice fields from a file.

    Returns (fields_dict, method). Raises ValueError for unsupported files;
    other failures (bad JSON, API errors) propagate to the caller.
    """
    strategy = detect_strategy(blob_name, data)
    if strategy == "unsupported":
        raise ValueError(f"Unsupported file type: {blob_name}")
    if strategy == "text":
        return _chat_extract_text(client, deployment, _pdf_text(data)), "text+gpt4o"
    if strategy == "vision-pdf":
        return _chat_extract_images(client, deployment, _pdf_to_png_pages(data)), "vision+gpt4o"
    return _chat_extract_images(client, deployment, [_image_to_png(data)]), "vision+gpt4o"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_extraction.py -v`
Expected: PASS — 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app/extraction.py function_app/tests/test_extraction.py
git commit -m "Add GPT-4o text and vision extraction"
```

---

## Task 4: Cosmos record assembly and upsert

**Files:**
- Create: `function_app/cosmos_writer.py`
- Test: `function_app/tests/test_cosmos_writer.py`

- [ ] **Step 1: Write the failing test**

Create `function_app/tests/test_cosmos_writer.py`:

```python
from unittest.mock import MagicMock

import cosmos_writer


def test_record_id_is_deterministic():
    assert cosmos_writer.record_id("a.pdf") == cosmos_writer.record_id("a.pdf")
    assert cosmos_writer.record_id("a.pdf") != cosmos_writer.record_id("b.pdf")


def test_build_record_extracted():
    extracted = {"invoice_number": "INV-9", "supplier_name": "Acme", "total_amount": 100.0}
    record = cosmos_writer.build_record("inv.pdf", extracted=extracted, method="text+gpt4o")
    assert record["id"] == cosmos_writer.record_id("inv.pdf")
    assert record["blob_name"] == "inv.pdf"
    assert record["invoice_number"] == "INV-9"
    assert record["supplier_name"] == "Acme"
    assert record["method"] == "text+gpt4o"
    assert record["status"] == "extracted"
    assert record["error"] is None
    assert record["processed_at"]  # ISO timestamp present


def test_build_record_missing_supplier_defaults_to_unknown():
    record = cosmos_writer.build_record("inv.pdf", extracted={}, method="text+gpt4o")
    assert record["supplier_name"] == "unknown"


def test_build_record_error():
    record = cosmos_writer.build_record("bad.pdf", status="error", error="boom")
    assert record["status"] == "error"
    assert record["error"] == "boom"
    assert record["supplier_name"] == "unknown"
    assert record["invoice_number"] is None


def test_upsert_calls_container():
    container = MagicMock()
    record = {"id": "x"}
    cosmos_writer.upsert(container, record)
    container.upsert_item.assert_called_once_with(record)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_cosmos_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cosmos_writer'`

- [ ] **Step 3: Write minimal implementation**

Create `function_app/cosmos_writer.py`:

```python
"""Assemble invoice records and persist them to Cosmos DB."""

import hashlib
from datetime import datetime, timezone

# Invoice fields carried from extraction into the stored record.
INVOICE_FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "buyer_name",
    "total_amount",
    "currency",
    "subtotal",
    "tax_amount",
    "tax_rate",
    "due_date",
    "po_number",
    "payment_terms",
    "line_items",
]


def record_id(blob_name: str) -> str:
    """A deterministic document id, so re-uploading a file upserts cleanly."""
    return hashlib.sha1(blob_name.encode("utf-8")).hexdigest()


def build_record(
    blob_name: str,
    extracted: dict | None = None,
    method: str | None = None,
    status: str = "extracted",
    error: str | None = None,
) -> dict:
    """Build a Cosmos document from extracted fields (or an error result).

    `supplier_name` is the container partition key, so it is never null —
    it falls back to 'unknown'.
    """
    extracted = extracted or {}
    record = {field: extracted.get(field) for field in INVOICE_FIELDS}
    record["id"] = record_id(blob_name)
    record["blob_name"] = blob_name
    record["method"] = method
    record["supplier_name"] = record.get("supplier_name") or "unknown"
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    record["status"] = status
    record["error"] = error
    return record


def upsert(container, record: dict) -> None:
    """Upsert a record into the Cosmos container."""
    container.upsert_item(record)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_cosmos_writer.py -v`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app/cosmos_writer.py function_app/tests/test_cosmos_writer.py
git commit -m "Add Cosmos record assembly and upsert"
```

---

## Task 5: Search index schema and document builders

**Files:**
- Create: `function_app/search_indexer.py`
- Test: `function_app/tests/test_search_indexer.py`

- [ ] **Step 1: Write the failing test**

Create `function_app/tests/test_search_indexer.py`:

```python
import search_indexer


def test_build_index_has_key_and_vector_field():
    index = search_indexer.build_index("invoices-idx")
    assert index.name == "invoices-idx"
    fields = {f.name: f for f in index.fields}
    assert fields["id"].key is True
    assert "content" in fields
    vector = fields["content_vector"]
    assert vector.vector_search_dimensions == search_indexer.EMBEDDING_DIMENSIONS


def test_build_content_summary_includes_core_fields():
    record = {
        "invoice_number": "INV-7",
        "supplier_name": "Acme",
        "buyer_name": "Globex",
        "invoice_date": "2024-03-01",
        "total_amount": 500.0,
        "currency": "EUR",
        "line_items": [{"description": "Widget"}],
    }
    summary = search_indexer.build_content_summary(record)
    assert "INV-7" in summary
    assert "Acme" in summary
    assert "Widget" in summary


def test_build_search_document_maps_fields_and_floats():
    record = {
        "id": "abc",
        "supplier_name": "Acme",
        "buyer_name": "Globex",
        "invoice_number": "INV-7",
        "po_number": None,
        "currency": "EUR",
        "invoice_date": "2024-03-01",
        "due_date": None,
        "blob_name": "inv.pdf",
        "total_amount": "500.0",
        "subtotal": None,
        "tax_amount": "not-a-number",
    }
    doc = search_indexer.build_search_document(record, "summary text", [0.1, 0.2])
    assert doc["id"] == "abc"
    assert doc["content"] == "summary text"
    assert doc["content_vector"] == [0.1, 0.2]
    assert doc["total_amount"] == 500.0
    assert doc["subtotal"] is None
    assert doc["tax_amount"] is None  # unparseable value coerced to None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_search_indexer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'search_indexer'`

- [ ] **Step 3: Write minimal implementation**

Create `function_app/search_indexer.py`:

```python
"""Azure AI Search: index schema, content summary, embedding, and document push."""

from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

# text-embedding-3-large default output dimensionality.
EMBEDDING_DIMENSIONS = 3072

# Numeric fields stored as Edm.Double in the index.
NUMERIC_FIELDS = ("total_amount", "subtotal", "tax_amount")


def build_index(index_name: str) -> SearchIndex:
    """Construct the SearchIndex definition for invoice records."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="supplier_name", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="buyer_name", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="invoice_number", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="po_number", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="currency", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="invoice_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="due_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="total_amount", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="subtotal", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="tax_amount", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="blob_name", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="invoice-hnsw",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="invoice-hnsw-algo")],
        profiles=[
            VectorSearchProfile(
                name="invoice-hnsw",
                algorithm_configuration_name="invoice-hnsw-algo",
            )
        ],
    )
    return SearchIndex(name=index_name, fields=fields, vector_search=vector_search)


def _as_float(value):
    """Coerce a value to float, or None if it is missing/unparseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_content_summary(record: dict) -> str:
    """Synthesize a plain-text paragraph describing an invoice — the text
    that gets embedded for vector search."""
    parts = [
        f"Invoice {record.get('invoice_number') or 'n/a'}",
        f"from supplier {record.get('supplier_name') or 'unknown'}",
        f"to buyer {record.get('buyer_name') or 'n/a'}",
        f"dated {record.get('invoice_date') or 'n/a'}",
        f"total {record.get('total_amount') or 'n/a'} {record.get('currency') or ''}".strip(),
    ]
    line_items = record.get("line_items")
    if isinstance(line_items, list) and line_items:
        descriptions = ", ".join(
            str(item.get("description", "")).strip()
            for item in line_items
            if isinstance(item, dict) and item.get("description")
        )
        if descriptions:
            parts.append(f"line items: {descriptions}")
    return ". ".join(parts) + "."


def build_search_document(record: dict, content: str, vector: list) -> dict:
    """Map a Cosmos record plus its embedding to an AI Search document."""
    doc = {
        "id": record["id"],
        "supplier_name": record.get("supplier_name"),
        "buyer_name": record.get("buyer_name"),
        "invoice_number": record.get("invoice_number"),
        "po_number": record.get("po_number"),
        "currency": record.get("currency"),
        "invoice_date": record.get("invoice_date"),
        "due_date": record.get("due_date"),
        "blob_name": record.get("blob_name"),
        "content": content,
        "content_vector": vector,
    }
    for field in NUMERIC_FIELDS:
        doc[field] = _as_float(record.get(field))
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_search_indexer.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app/search_indexer.py function_app/tests/test_search_indexer.py
git commit -m "Add Search index schema and document builders"
```

---

## Task 6: Embedding, index creation, and document push

**Files:**
- Modify: `function_app/search_indexer.py`
- Test: `function_app/tests/test_search_indexer.py`

- [ ] **Step 1: Write the failing test**

Append to `function_app/tests/test_search_indexer.py`:

```python
from unittest.mock import MagicMock


def test_ensure_index_creates_or_updates():
    index_client = MagicMock()
    search_indexer.ensure_index(index_client, "invoices-idx")
    index_client.create_or_update_index.assert_called_once()
    created = index_client.create_or_update_index.call_args[0][0]
    assert created.name == "invoices-idx"


def test_embed_returns_vector():
    openai_client = MagicMock()
    openai_client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2])]
    vector = search_indexer.embed(openai_client, "text-embedding-3-large", "hello")
    assert vector == [0.1, 0.2]
    openai_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-large", input="hello"
    )


def test_index_record_embeds_and_uploads():
    search_client = MagicMock()
    openai_client = MagicMock()
    openai_client.embeddings.create.return_value.data = [MagicMock(embedding=[0.3])]
    record = {"id": "abc", "supplier_name": "Acme", "invoice_number": "INV-1"}

    search_indexer.index_record(search_client, openai_client, "text-embedding-3-large", record)

    search_client.upload_documents.assert_called_once()
    uploaded = search_client.upload_documents.call_args.kwargs["documents"][0]
    assert uploaded["id"] == "abc"
    assert uploaded["content_vector"] == [0.3]
    assert uploaded["content"]  # summary populated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_search_indexer.py -v`
Expected: FAIL — `AttributeError: module 'search_indexer' has no attribute 'ensure_index'`

- [ ] **Step 3: Write minimal implementation**

Append to `function_app/search_indexer.py`:

```python
def ensure_index(index_client, index_name: str) -> None:
    """Create the index, or update it to match the schema. Idempotent."""
    index_client.create_or_update_index(build_index(index_name))


def embed(openai_client, deployment: str, text: str) -> list:
    """Return the embedding vector for `text`."""
    response = openai_client.embeddings.create(model=deployment, input=text)
    return response.data[0].embedding


def index_record(search_client, openai_client, embed_deployment: str, record: dict) -> None:
    """Embed an invoice record's summary and push the document to Search."""
    content = build_content_summary(record)
    vector = embed(openai_client, embed_deployment, content)
    document = build_search_document(record, content, vector)
    search_client.upload_documents(documents=[document])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_search_indexer.py -v`
Expected: PASS — 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app/search_indexer.py function_app/tests/test_search_indexer.py
git commit -m "Add embedding, index creation, and document push"
```

---

## Task 7: Blob trigger and orchestration

**Files:**
- Create: `function_app/function_app.py`
- Test: `function_app/tests/test_function_app.py`

- [ ] **Step 1: Write the failing test**

Create `function_app/tests/test_function_app.py`:

```python
from unittest.mock import MagicMock

import function_app

_CONFIG = {
    "gpt_deployment": "gpt-4o",
    "embed_deployment": "text-embedding-3-large",
    "search_index": "invoices-idx",
}


def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _chat_client(json_content):
    client = MagicMock()
    choice = MagicMock()
    choice.message = MagicMock(content=json_content)
    client.chat.completions.create.return_value.choices = [choice]
    client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1])]
    return client


def test_process_blob_success_path():
    function_app._index_ensured = False
    openai_client = _chat_client('{"invoice_number": "INV-1", "supplier_name": "Acme"}')
    cosmos_container = MagicMock()
    search_client = MagicMock()
    index_client = MagicMock()

    record = function_app.process_blob(
        "invoice.png", _png(), _CONFIG,
        openai_client, cosmos_container, search_client, index_client,
    )

    assert record["status"] == "extracted"
    index_client.create_or_update_index.assert_called_once()
    cosmos_container.upsert_item.assert_called_once()
    search_client.upload_documents.assert_called_once()


def test_process_blob_extraction_failure_path():
    function_app._index_ensured = False
    cosmos_container = MagicMock()
    search_client = MagicMock()
    index_client = MagicMock()

    record = function_app.process_blob(
        "notes.txt", b"not an invoice", _CONFIG,
        MagicMock(), cosmos_container, search_client, index_client,
    )

    assert record["status"] == "error"
    assert "Unsupported" in record["error"]
    cosmos_container.upsert_item.assert_called_once()
    search_client.upload_documents.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd function_app && pytest tests/test_function_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'function_app'`

- [ ] **Step 3: Write minimal implementation**

Create `function_app/function_app.py`:

```python
"""Azure Function: process_invoice — blob-triggered invoice ingestion.

A new blob in the `invoices/` container triggers extraction with GPT-4o,
an upsert to Cosmos DB, and a push to the Azure AI Search index.
"""

import logging
import os

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI

import cosmos_writer
import extraction
import search_indexer

app = func.FunctionApp()

# Ensures the Search index is created once per worker process (cold start).
_index_ensured = False


def load_config() -> dict:
    """Read configuration from Function App settings."""
    return {
        "openai_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
        "openai_api_version": os.environ["AZURE_OPENAI_API_VERSION"],
        "gpt_deployment": os.environ["AZURE_OPENAI_GPT_DEPLOYMENT"],
        "embed_deployment": os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        "cosmos_endpoint": os.environ["COSMOS_ENDPOINT"],
        "cosmos_database": os.environ["COSMOS_DATABASE"],
        "cosmos_container": os.environ["COSMOS_CONTAINER"],
        "search_endpoint": os.environ["SEARCH_ENDPOINT"],
        "search_index": os.environ["SEARCH_INDEX"],
    }


def build_clients(config: dict):
    """Construct Azure SDK clients using the Function's managed identity.

    Returns (openai_client, cosmos_container, search_client, index_client).
    """
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    openai_client = AzureOpenAI(
        azure_endpoint=config["openai_endpoint"],
        azure_ad_token_provider=token_provider,
        api_version=config["openai_api_version"],
    )
    cosmos_container = (
        CosmosClient(config["cosmos_endpoint"], credential=credential)
        .get_database_client(config["cosmos_database"])
        .get_container_client(config["cosmos_container"])
    )
    search_client = SearchClient(
        config["search_endpoint"], config["search_index"], credential=credential
    )
    index_client = SearchIndexClient(config["search_endpoint"], credential=credential)
    return openai_client, cosmos_container, search_client, index_client


def process_blob(blob_name, data, config, openai_client, cosmos_container,
                 search_client, index_client) -> dict:
    """Core ingestion logic. Returns the record written to Cosmos.

    Extraction failures are caught and stored as error records; transient
    infrastructure errors propagate so the Functions host retries the blob.
    """
    global _index_ensured
    if not _index_ensured:
        search_indexer.ensure_index(index_client, config["search_index"])
        _index_ensured = True

    try:
        extracted, method = extraction.extract(
            openai_client, config["gpt_deployment"], blob_name, data
        )
    except Exception as exc:  # extraction failure — record it, do not index
        logging.exception("Extraction failed for %s", blob_name)
        record = cosmos_writer.build_record(blob_name, status="error", error=str(exc))
        cosmos_writer.upsert(cosmos_container, record)
        return record

    record = cosmos_writer.build_record(blob_name, extracted=extracted, method=method)
    cosmos_writer.upsert(cosmos_container, record)
    search_indexer.index_record(
        search_client, openai_client, config["embed_deployment"], record
    )
    logging.info("Indexed invoice %s", blob_name)
    return record


@app.blob_trigger(arg_name="blob", path="invoices/{name}", connection="AzureWebJobsStorage")
def process_invoice(blob: func.InputStream):
    """Blob trigger entrypoint for the `invoices/` container."""
    blob_name = blob.name.split("/", 1)[-1]
    logging.info("process_invoice triggered for %s", blob_name)
    config = load_config()
    clients = build_clients(config)
    process_blob(blob_name, blob.read(), config, *clients)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd function_app && pytest tests/test_function_app.py -v`
Expected: PASS — 2 tests pass.

- [ ] **Step 5: Run the full test suite**

Run: `cd function_app && pytest -v`
Expected: PASS — all 20 tests pass.

- [ ] **Step 6: Commit**

```bash
git add function_app/function_app.py function_app/tests/test_function_app.py
git commit -m "Add blob trigger and ingestion orchestration"
```

---

## Task 8: Deploy and verify end-to-end

**Files:** none (deployment + manual verification)

This task needs the Azure Functions Core Tools (`func`) and `az` CLI, both
authenticated against the sandbox subscription.

- [ ] **Step 1: Deploy the Function code**

Run:
```bash
cd function_app && func azure functionapp publish func-invoice-rag-infim0 --python
```
Expected: upload completes; output lists the `process_invoice` function with an
HTTP-less blob trigger.

- [ ] **Step 2: Confirm the function registered**

Run:
```bash
az functionapp function list \
  --subscription 21a1faed-77bc-4545-a743-eda9becaebc6 \
  -g rg-invoice-rag -n func-invoice-rag-infim0 \
  --query "[].name" -o tsv
```
Expected: `process_invoice`

- [ ] **Step 3: Upload a text-based PDF invoice**

Run (use any sample text-based PDF invoice):
```bash
az storage blob upload \
  --account-name stinvoiceraginfim0 --auth-mode login \
  -c invoices -f ./sample-invoice.pdf -n sample-invoice.pdf
```
Expected: upload succeeds. Within ~1 minute the blob trigger fires.

- [ ] **Step 4: Verify the Cosmos record**

Run:
```bash
az cosmosdb sql query \
  --subscription 21a1faed-77bc-4545-a743-eda9becaebc6 \
  --account-name cosmos-invoice-rag-infim0 -g rg-invoice-rag \
  --database-name invoices --container-name records \
  --query-text "SELECT c.id, c.blob_name, c.supplier_name, c.total_amount, c.status FROM c"
```
Expected: one row with `status` = `extracted` and the invoice's fields populated.

> If `az cosmosdb sql query` is unavailable in the installed CLI version, open
> the Cosmos DB Data Explorer in the Azure Portal and run the same SELECT.

- [ ] **Step 5: Verify the Search document**

Run:
```bash
az rest --method get \
  --url "https://srch-invoice-rag-infim0.search.windows.net/indexes/invoices-idx/docs/\$count?api-version=2024-07-01" \
  --resource "https://search.azure.com"
```
Expected: a count of `1` (or more).

- [ ] **Step 6: Verify the error path**

Run:
```bash
echo "not an invoice" > broken.txt
az storage blob upload \
  --account-name stinvoiceraginfim0 --auth-mode login \
  -c invoices -f ./broken.txt -n broken.txt
```
Then re-run the Step 4 query. Expected: a `broken.txt` row with `status` = `error`
and a populated `error` message; no matching document was added to Search.

- [ ] **Step 7: Verify the scanned-PDF path**

Upload a scanned/image-only PDF or an image invoice the same way as Step 3, then
re-run the Step 4 query. Expected: a new `status` = `extracted` row whose `method`
is `vision+gpt4o`.

- [ ] **Step 8: Commit any deployment notes**

If sample files or notes were added under `function_app/`, commit them:
```bash
git add -A
git commit -m "Add deployment verification samples"
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- §3 repository layout → Task 1
- §4 PyMuPDF PDF rendering → Task 2 (`_pdf_to_png_pages`)
- §5 processing flow → Task 7 (`process_blob`)
- §6.1 Cosmos document → Task 4 (`build_record`)
- §6.2 Search index schema → Task 5 (`build_index`)
- §7 managed-identity auth → Task 7 (`build_clients`)
- §8 index creation on cold start → Task 7 (`_index_ensured` guard)
- §9 error handling → Task 7 (extraction try/except) + Task 4 (error record)
- §11 verification → Task 8

**Placeholder scan** — no TBD/TODO; every code step shows complete code.

**Type consistency** — `extract()` returns `(dict, str)`, consumed as
`extracted, method` in `process_blob`. `build_record()` returns the record dict
consumed by `upsert()` and `index_record()`. `record["id"]` set in `build_record`
is read in `build_search_document`. `ensure_index`, `embed`, `index_record`,
`build_index` names are consistent across Tasks 5–7. Config keys (`gpt_deployment`,
`embed_deployment`, `search_index`) match between `load_config` and `process_blob`.
