# Local Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-first mode where SQLite + ChromaDB replace Azure Cosmos DB and Azure AI Search, while keeping Azure OpenAI (GPT-4o + embeddings) for extraction and RAG — all auto-detected from env vars with zero code changes in the Streamlit pages.

**Architecture:** `build_agent()` in `agent.py` checks for `SEARCH_ENDPOINT`; if absent it delegates to `build_local_agent()` in the new `local_agent.py`. The local agent owns a ChromaDB collection for vector search and delegates metadata persistence to `local_store.py` (SQLite). The upload page detects local mode by the absence of `STORAGE_ACCOUNT_NAME` and runs `extractor.process_file()` inline (no blob upload, no polling). The cloud path is completely unchanged.

**Tech Stack:** Python stdlib `sqlite3`, `chromadb>=0.5`, Azure OpenAI via API key (not managed identity), `extractor.process_file()` for inline extraction, `search_indexer.build_content_summary()` reused for embedding text.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `local_store.py` | **Create** | SQLite CRUD — upsert, query, delete |
| `local_agent.py` | **Create** | ChromaDB vector store + `LocalInvoiceAgent` |
| `agent.py` | **Modify** | `build_agent()` auto-detects mode |
| `pages/1_Upload.py` | **Modify** | Local extraction path (inline, no polling) |
| `app.py` | **Modify** | Local admin panel (clear/export from SQLite) |
| `requirements.txt` | **Modify** | Add `chromadb>=0.5.0` |
| `.env.local.sample` | **Create** | Minimal env vars for local mode |

Data lives in `./data/` (gitignored via `*.db` and a new `data/` entry).

---

## Task 1: SQLite Storage Layer

**Files:**
- Create: `local_store.py`

- [ ] **Step 0: Create tests directory**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_local_store.py`:

```python
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point at a temp DB so tests don't touch ./data/invoices.db
os.environ["LOCAL_DB_PATH"] = ":memory:"

import local_store

SAMPLE = {
    "id": "abc123",
    "blob_name": "test.pdf",
    "supplier_name": "Acme Corp",
    "supplier_name_en": "Acme Corp",
    "invoice_number": "INV-001",
    "invoice_date": "2024-01-15",
    "total_amount": 1234.56,
    "currency": "USD",
    "buyer_name": "Buyer Ltd",
    "buyer_name_en": "Buyer Ltd",
    "subtotal": 1000.0,
    "tax_amount": 234.56,
    "due_date": "2024-02-15",
    "po_number": "PO-99",
    "content": "Invoice INV-001 from Acme Corp to Buyer Ltd.",
}


def test_upsert_and_count():
    local_store.upsert_invoice(SAMPLE)
    assert local_store.get_invoice_count() == 1


def test_get_all_returns_record():
    local_store.upsert_invoice(SAMPLE)
    rows = local_store.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["supplier_name"] == "Acme Corp"


def test_currencies():
    local_store.upsert_invoice(SAMPLE)
    assert "USD" in local_store.get_currencies()


def test_get_by_blob():
    local_store.upsert_invoice(SAMPLE)
    row = local_store.get_invoice_by_blob("test.pdf")
    assert row is not None
    assert row["invoice_number"] == "INV-001"


def test_upsert_is_idempotent():
    local_store.upsert_invoice(SAMPLE)
    local_store.upsert_invoice(SAMPLE)
    assert local_store.get_invoice_count() == 1


def test_delete_all():
    local_store.upsert_invoice(SAMPLE)
    deleted = local_store.delete_all()
    assert deleted == 1
    assert local_store.get_invoice_count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/sandijsbalodis/Desktop/homework task"
pytest tests/test_local_store.py -v
```
Expected: `ModuleNotFoundError: No module named 'local_store'`

- [ ] **Step 3: Implement `local_store.py`**

```python
"""SQLite storage for local mode — replaces Azure Cosmos DB."""

import os
import sqlite3
from contextlib import contextmanager

_DB_PATH = os.environ.get("LOCAL_DB_PATH") or os.path.join(
    os.path.dirname(__file__), "data", "invoices.db"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              TEXT PRIMARY KEY,
    blob_name       TEXT,
    supplier_name   TEXT,
    supplier_name_en TEXT,
    invoice_number  TEXT,
    invoice_date    TEXT,
    total_amount    REAL,
    currency        TEXT,
    buyer_name      TEXT,
    buyer_name_en   TEXT,
    subtotal        REAL,
    tax_amount      REAL,
    due_date        TEXT,
    po_number       TEXT,
    content         TEXT
)
"""

_FIELDS = [
    "id", "blob_name", "supplier_name", "supplier_name_en", "invoice_number",
    "invoice_date", "total_amount", "currency", "buyer_name", "buyer_name_en",
    "subtotal", "tax_amount", "due_date", "po_number", "content",
]


@contextmanager
def _conn():
    if _DB_PATH != ":memory:":
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute(_SCHEMA)
        con.commit()
        yield con
    finally:
        con.close()


def upsert_invoice(record: dict) -> None:
    placeholders = ", ".join("?" for _ in _FIELDS)
    cols = ", ".join(_FIELDS)
    values = [record.get(f) for f in _FIELDS]
    with _conn() as con:
        con.execute(
            f"INSERT OR REPLACE INTO invoices ({cols}) VALUES ({placeholders})",
            values,
        )
        con.commit()


def get_all_invoices() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM invoices").fetchall()
    return [dict(r) for r in rows]


def get_invoice_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


def get_currencies() -> list[str]:
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT currency FROM invoices WHERE currency IS NOT NULL"
        ).fetchall()
    return sorted(r[0] for r in rows)


def get_invoice_by_blob(blob_name: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM invoices WHERE blob_name = ?", (blob_name,)
        ).fetchone()
    return dict(row) if row else None


def delete_all() -> int:
    with _conn() as con:
        count = con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        con.execute("DELETE FROM invoices")
        con.commit()
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_local_store.py -v
```
Expected: 6 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add local_store.py tests/test_local_store.py
git commit -m "feat: local SQLite storage layer"
```

---

## Task 2: ChromaDB Vector Store + LocalInvoiceAgent

**Files:**
- Create: `local_agent.py`

- [ ] **Step 1: Install chromadb and add to requirements**

```bash
pip install "chromadb>=0.5.0"
```

Open `requirements.txt` and add after the `streamlit` line:
```
chromadb>=0.5.0                 # Local vector store for local mode
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_local_agent.py`:

```python
import os, sys, types, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["LOCAL_DB_PATH"] = ":memory:"
os.environ["LOCAL_CHROMA_PATH"] = ":memory:"

# Stub the openai client and extractor so the test is offline
import local_store

SAMPLE_RECORD = {
    "id": "def456",
    "blob_name": "invoice.pdf",
    "supplier_name": "Test Supplier",
    "supplier_name_en": "Test Supplier",
    "invoice_number": "INV-999",
    "invoice_date": "2024-06-01",
    "total_amount": 500.0,
    "currency": "EUR",
    "buyer_name": "Buyer Co",
    "buyer_name_en": "Buyer Co",
    "subtotal": 413.22,
    "tax_amount": 86.78,
    "due_date": None,
    "po_number": None,
    "content": "Invoice INV-999 from Test Supplier to Buyer Co dated 2024-06-01 total 500.0 EUR.",
}


class _FakeEmbedding:
    def create(self, model, input):  # noqa: A002
        class _Data:
            embedding = [0.1] * 3072
        class _Resp:
            data = [_Data()]
        return _Resp()


class _FakeChat:
    def create(self, model, messages, temperature):
        class _Choice:
            class message:
                content = "Test answer."
        class _Resp:
            choices = [_Choice()]
        return _Resp()


class _FakeOpenAI:
    embeddings = _FakeEmbedding()
    chat = type("Chat", (), {"completions": _FakeChat()})()


from local_agent import LocalInvoiceAgent
import chromadb


def _make_agent():
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("invoices-test")
    return LocalInvoiceAgent(
        store=local_store,
        chroma_collection=collection,
        openai_client=_FakeOpenAI(),
        gpt_deployment="gpt-4o",
        embedding_deployment="text-embedding-3-large",
    )


def test_index_and_stats():
    agent = _make_agent()
    agent.index_invoice(SAMPLE_RECORD)
    stats = agent.get_stats()
    assert stats["total_invoices"] == 1
    assert "EUR" in stats["currencies"]


def test_ask_returns_answer():
    agent = _make_agent()
    agent.index_invoice(SAMPLE_RECORD)
    response = agent.ask("What is the total?")
    assert response.answer == "Test answer."
    assert response.results is not None


def test_ask_error_is_graceful():
    agent = _make_agent()
    # No documents indexed — should still return an answer (empty context)
    response = agent.ask("What invoices exist?")
    assert isinstance(response.answer, str)
    assert response.error is None
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_local_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'local_agent'`

- [ ] **Step 4: Implement `local_agent.py`**

```python
"""Local ChromaDB vector store + LocalInvoiceAgent — replaces Azure AI Search."""

import hashlib
import os
import sys

import chromadb
from openai import AzureOpenAI

import local_store as _default_store

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "function_app"))
from search_indexer import build_content_summary  # noqa: E402

from agent import AgentResponse, ANSWER_SYSTEM_PROMPT, HISTORY_LIMIT, TOP_K

import json

_CHROMA_PATH = os.environ.get("LOCAL_CHROMA_PATH") or os.path.join(
    os.path.dirname(__file__), "data", "chroma"
)


class LocalInvoiceAgent:
    """RAG agent backed by ChromaDB + SQLite instead of Azure AI Search + Cosmos."""

    def __init__(self, store, chroma_collection, openai_client, gpt_deployment, embedding_deployment):
        self._store = store
        self._col = chroma_collection
        self.openai_client = openai_client
        self.gpt_deployment = gpt_deployment
        self.embedding_deployment = embedding_deployment
        self._history: list[dict] = []

    def _embed(self, text: str) -> list[float]:
        response = self.openai_client.embeddings.create(
            model=self.embedding_deployment, input=text
        )
        return response.data[0].embedding

    def index_invoice(self, record: dict) -> None:
        """Embed a record and add it to ChromaDB + SQLite."""
        content = build_content_summary(record)
        vector = self._embed(content)
        doc_id = record.get("id") or hashlib.sha256(
            record.get("blob_name", "").encode()
        ).hexdigest()[:32]

        full_record = {**record, "id": doc_id, "content": content}
        self._store.upsert_invoice(full_record)

        self._col.upsert(
            ids=[doc_id],
            embeddings=[vector],
            documents=[content],
            metadatas=[{
                k: (str(v) if v is not None else "")
                for k, v in full_record.items()
                if k not in ("content",) and not isinstance(v, (list, dict))
            }],
        )

    def retrieve(self, question: str) -> list[dict]:
        """Embed the question and return the top-K closest invoice records."""
        vector = self._embed(question)
        n = min(TOP_K, self._col.count())
        if n == 0:
            return []
        results = self._col.query(
            query_embeddings=[vector],
            n_results=n,
            include=["metadatas", "documents"],
        )
        docs = []
        for meta, doc in zip(results["metadatas"][0], results["documents"][0]):
            row = dict(meta)
            row["content"] = doc
            # Restore numeric types
            for field in ("total_amount", "subtotal", "tax_amount"):
                if row.get(field):
                    try:
                        row[field] = float(row[field])
                    except ValueError:
                        row[field] = None
            docs.append(row)
        return docs

    def _generate_answer(self, question: str, docs: list[dict]) -> str:
        records_text = json.dumps(docs, indent=2, default=str) if docs else "[]"
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            *self._history[-HISTORY_LIMIT:],
            {
                "role": "user",
                "content": f"Question: {question}\n\nInvoice records:\n{records_text}",
            },
        ]
        response = self.openai_client.chat.completions.create(
            model=self.gpt_deployment, messages=messages, temperature=0.3
        )
        return response.choices[0].message.content.strip()

    def ask(self, question: str) -> AgentResponse:
        try:
            docs = self.retrieve(question)
        except Exception as e:
            return AgentResponse(
                answer="I couldn't reach the local invoice index. Please try again.",
                error=str(e),
            )
        try:
            answer = self._generate_answer(question, docs)
        except Exception as e:
            return AgentResponse(
                answer="I retrieved the invoices but couldn't generate an answer.",
                results=docs,
                error=str(e),
            )
        self._history.append({"role": "user", "content": question})
        self._history.append({"role": "assistant", "content": answer})
        return AgentResponse(answer=answer, results=docs)

    def get_stats(self) -> dict:
        try:
            return {
                "total_invoices": self._store.get_invoice_count(),
                "currencies": self._store.get_currencies(),
            }
        except Exception:
            return {}


def build_local_agent() -> LocalInvoiceAgent:
    """Construct a LocalInvoiceAgent from environment config."""
    from agent import _require_env
    openai_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    api_key = _require_env("AZURE_OPENAI_API_KEY")
    gpt_deployment = _require_env("AZURE_OPENAI_GPT_DEPLOYMENT")
    embedding_deployment = _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        api_key=api_key,
        api_version=api_version,
    )

    if _CHROMA_PATH == ":memory:":
        chroma_client = chromadb.EphemeralClient()
    else:
        os.makedirs(_CHROMA_PATH, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=_CHROMA_PATH)

    collection = chroma_client.get_or_create_collection(
        name="invoices",
        metadata={"hnsw:space": "cosine"},
    )

    return LocalInvoiceAgent(
        store=_default_store,
        chroma_collection=collection,
        openai_client=openai_client,
        gpt_deployment=gpt_deployment,
        embedding_deployment=embedding_deployment,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_local_agent.py -v
```
Expected: 3 tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add local_agent.py tests/test_local_agent.py requirements.txt
git commit -m "feat: local ChromaDB vector store and LocalInvoiceAgent"
```

---

## Task 3: Auto-detect Mode in agent.py

**Files:**
- Modify: `agent.py:167-183`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_local_agent.py`:

```python
def test_build_agent_uses_local_when_no_search_endpoint(monkeypatch):
    monkeypatch.delenv("SEARCH_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-4o")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

    # Patch chromadb and AzureOpenAI so no real connections are made
    import chromadb as _chroma
    monkeypatch.setattr(_chroma, "PersistentClient", lambda **kw: _chroma.EphemeralClient())

    from agent import build_agent
    from local_agent import LocalInvoiceAgent
    agent = build_agent()
    assert isinstance(agent, LocalInvoiceAgent)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_local_agent.py::test_build_agent_uses_local_when_no_search_endpoint -v
```
Expected: FAILED — `build_agent()` raises `EnvironmentError` about `SEARCH_ENDPOINT`.

- [ ] **Step 3: Modify `build_agent()` in `agent.py`**

Replace lines 167-183:

```python
def build_agent():
    """Construct an agent from environment config.

    Returns a LocalInvoiceAgent (ChromaDB + SQLite) when SEARCH_ENDPOINT is
    absent, or an InvoiceAgent (Azure AI Search) when it is set.
    """
    if not os.environ.get("SEARCH_ENDPOINT"):
        from local_agent import build_local_agent
        return build_local_agent()

    search_endpoint = _require_env("SEARCH_ENDPOINT")
    search_index = _require_env("SEARCH_INDEX")
    openai_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    gpt_deployment = _require_env("AZURE_OPENAI_GPT_DEPLOYMENT")
    embedding_deployment = _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    credential = DefaultAzureCredential()
    search_client = SearchClient(search_endpoint, search_index, credential)
    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        azure_ad_token_provider=get_bearer_token_provider(credential, _COGNITIVE_SCOPE),
        api_version=api_version,
    )
    return InvoiceAgent(search_client, openai_client, gpt_deployment, embedding_deployment)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_local_agent.py -v
```
Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_local_agent.py
git commit -m "feat: auto-detect local vs cloud mode in build_agent()"
```

---

## Task 4: Local Upload Path in pages/1_Upload.py

**Files:**
- Modify: `pages/1_Upload.py`

The current upload page hard-stops if `STORAGE_ACCOUNT_NAME` is unset. In local mode, we skip blob upload entirely and extract inline using `extractor.process_file()`.

- [ ] **Step 1: Add temp-file extraction helper**

In `pages/1_Upload.py`, replace the `STORAGE_ACCOUNT` missing check and add local extraction. The full modified file:

Replace lines 96-101 (the `STORAGE_ACCOUNT` guard block):

```python
IS_LOCAL_MODE = not STORAGE_ACCOUNT
```

Then replace the entire `if st.button("Upload and process", type="primary"):` block with:

```python
if st.button("Upload and process", type="primary"):
    if IS_LOCAL_MODE:
        _run_local_extraction(uploaded_files)
    else:
        _run_cloud_upload(uploaded_files)
```

Add both helpers above the button. Full implementation of `_run_local_extraction`:

```python
import hashlib
import tempfile
import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))

from extractor import get_client, process_file as _extract_file


def _run_local_extraction(uploaded_files):
    """Extract invoices inline (no Azure Storage, no polling)."""
    if st.session_state.agent is None:
        st.error("Agent not configured. Check your .env.")
        return

    st.subheader("Extracting…")
    client, model = get_client()
    progress = st.progress(0)
    results = []

    for i, f in enumerate(uploaded_files):
        suffix = _os.path.splitext(f.name)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name

        try:
            with st.spinner(f"Extracting {f.name}…"):
                record = _extract_file(client, tmp_path, model)
        finally:
            _os.unlink(tmp_path)

        if record.get("error"):
            st.error(f"❌ {f.name}: {record['error']}")
            progress.progress((i + 1) / len(uploaded_files))
            continue

        blob_name = f.name
        doc_id = hashlib.sha256(blob_name.encode()).hexdigest()[:32]
        index_record = {
            "id": doc_id,
            "blob_name": blob_name,
            "supplier_name": record.get("supplier_name"),
            "supplier_name_en": record.get("supplier_name"),  # no translation in local mode
            "invoice_number": record.get("invoice_number"),
            "invoice_date": record.get("invoice_date"),
            "total_amount": record.get("total_amount"),
            "currency": record.get("currency"),
            "buyer_name": record.get("buyer_name"),
            "buyer_name_en": record.get("buyer_name"),
            "subtotal": record.get("subtotal"),
            "tax_amount": record.get("tax_amount"),
            "due_date": record.get("due_date"),
            "po_number": record.get("po_number"),
        }
        st.session_state.agent.index_invoice(index_record)

        supplier = index_record.get("supplier_name") or "—"
        inv_num = index_record.get("invoice_number") or "—"
        total = index_record.get("total_amount")
        currency = index_record.get("currency") or ""
        amount_str = f"{total:,.2f} {currency}".strip() if total else "—"
        st.success(f"✓ **{blob_name}** — {supplier} · {inv_num} · {amount_str}")
        results.append(index_record)
        progress.progress((i + 1) / len(uploaded_files))

    if results:
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            st.download_button(
                label="⬇ Download CSV",
                data=_build_csv(results),
                file_name=f"invoices_{date.today().isoformat()}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with action_col2:
            if st.button("💬 Chat now →", use_container_width=True, type="primary"):
                st.switch_page("pages/2_Chat.py")
```

Wrap the existing cloud upload/polling code into `_run_cloud_upload(uploaded_files)` — move the current block verbatim into that function.

- [ ] **Step 2: Test manually**

```bash
cd "/Users/sandijsbalodis/Desktop/homework task"
cp .env .env.cloud.bak   # back up cloud env
# Create a minimal .env.local with just OpenAI vars (copy from .env.local.sample after Task 6)
# Then:
DOTENV_PATH=.env.local streamlit run app.py
```

Upload one of the sample PDFs from `sample_invoices/` (or any PDF on disk). Expected: extraction runs inline, success row appears, no blob/polling.

- [ ] **Step 3: Commit**

```bash
git add pages/1_Upload.py
git commit -m "feat: local extraction path in upload page"
```

---

## Task 5: Local Admin Panel in app.py

**Files:**
- Modify: `app.py:76-168`

The cloud admin panel uses Cosmos/Search. In local mode those env vars don't exist; replace the admin UI with SQLite/ChromaDB equivalents.

- [ ] **Step 1: Modify the `⚙ Admin` expander**

Replace the contents of the `with st.expander("⚙ Admin"):` block (currently lines 77-168) with a mode-aware version:

```python
with st.expander("⚙ Admin"):
    if os.environ.get("SEARCH_ENDPOINT"):
        # ---- Cloud admin (unchanged) ----
        from sync import clear_all, export_csv, rebuild
        # ... (keep all existing cloud admin code here exactly as-is)
    else:
        # ---- Local admin ----
        import local_store

        st.caption("**Export** — download all locally stored invoices as CSV.")
        if st.session_state.get("admin_csv"):
            from datetime import date
            st.download_button(
                label="⬇ Export CSV",
                data=st.session_state["admin_csv"],
                file_name=f"invoices_{date.today().isoformat()}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            if st.button("⬇ Export CSV", use_container_width=True):
                import csv, io
                records = local_store.get_all_invoices()
                fields = [
                    "blob_name", "supplier_name", "invoice_number", "invoice_date",
                    "total_amount", "currency", "buyer_name", "subtotal",
                    "tax_amount", "due_date", "po_number",
                ]
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for r in records:
                    writer.writerow({k: (r.get(k) or "") for k in fields})
                st.session_state["admin_csv"] = buf.getvalue().encode("utf-8")
                st.rerun()

        st.divider()

        st.caption("**Clear** — permanently delete all locally stored invoices.")
        confirm = st.checkbox("I understand this will permanently delete all stored invoices")
        if st.button("🗑 Clear all invoices", disabled=not confirm, use_container_width=True):
            deleted = local_store.delete_all()
            if st.session_state.get("agent"):
                # Reset the ChromaDB collection via the agent
                try:
                    col = st.session_state.agent._col
                    col.delete(where={"blob_name": {"$ne": ""}})
                except Exception:
                    pass
            st.success(f"Cleared {deleted} invoice(s).")
            st.session_state.pop("agent", None)
            st.session_state.pop("admin_csv", None)
            st.rerun()
```

- [ ] **Step 2: Test manually**

With local `.env` active, open the Admin expander. Verify Export CSV downloads correctly after uploading invoices. Verify Clear deletes them and the index count on the home page drops to 0.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: local admin panel (SQLite export + clear)"
```

---

## Task 6: Env Sample + .gitignore + requirements.txt

**Files:**
- Create: `.env.local.sample`
- Modify: `.gitignore`
- Modify: `requirements.txt` (already done in Task 2, verify)

- [ ] **Step 1: Create `.env.local.sample`**

```bash
cat > .env.local.sample << 'EOF'
# Local mode — no Azure Storage, Cosmos DB, or AI Search needed.
# Copy to .env and fill in your Azure OpenAI values.

AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_GPT_DEPLOYMENT=gpt-4o
# extractor.py reads AZURE_OPENAI_DEPLOYMENT (different name — set both)
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Leave the following UNSET for local mode (their absence triggers local path):
# SEARCH_ENDPOINT=
# SEARCH_INDEX=
# STORAGE_ACCOUNT_NAME=
# COSMOS_ENDPOINT=
EOF
```

- [ ] **Step 2: Add data/ to .gitignore**

Open `.gitignore` and add:
```
# Local mode data (SQLite + ChromaDB)
data/
```

- [ ] **Step 3: Verify requirements.txt has chromadb**

```bash
grep chromadb requirements.txt
```
Expected: `chromadb>=0.5.0`

- [ ] **Step 4: Full end-to-end smoke test**

```bash
cd "/Users/sandijsbalodis/Desktop/homework task"
# Ensure .env has only local vars (AZURE_OPENAI_* only, no SEARCH_ENDPOINT)
streamlit run app.py
```

1. Home page loads — shows "0 invoices indexed"
2. Click "Upload Invoices" — upload a PDF
3. Extraction runs inline — success row shows supplier + amount
4. Click "Chat now" — ask "What invoices do I have?"
5. Agent answers from the indexed data
6. Admin panel → Export CSV downloads the record
7. Admin panel → Clear all → count returns to 0

- [ ] **Step 5: Commit**

```bash
git add .env.local.sample .gitignore requirements.txt
git commit -m "feat: local mode env sample, data/ gitignore, chromadb dependency"
```

---

## Done

All six tasks produce a working local mode. The cloud path (`SEARCH_ENDPOINT` set) is completely untouched — same Container App deployment continues to work without any changes.
