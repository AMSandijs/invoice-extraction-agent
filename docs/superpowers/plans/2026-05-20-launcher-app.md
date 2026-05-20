# Launcher App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-file Streamlit chat app into a three-screen launcher app (Home → Upload or Chat) with a double-clickable macOS launcher.

**Architecture:** `app.py` becomes the home screen with two navigation buttons; chat logic moves verbatim to `pages/2_Chat.py`; a new `pages/1_Upload.py` handles file upload to Azure Blob + polls AI Search for results + offers CSV download. A new `uploader.py` module owns the Blob upload logic. A `launch.command` shell script enables double-click launch on macOS.

**Tech Stack:** Streamlit ≥ 1.35 (multi-page, `st.switch_page`), `azure-storage-blob` (new), `azure-identity` (existing), `azure-search-documents` (existing), Python 3.10+

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `uploader.py` | Create | Azure Blob upload helper — one public function |
| `pages/2_Chat.py` | Create | Current `app.py` chat logic, moved verbatim + Back link |
| `app.py` | Rewrite | Home screen — centred launcher, two nav buttons |
| `pages/1_Upload.py` | Create | Upload screen — file picker, blob upload, polling, CSV, nav |
| `launch.command` | Create | macOS double-click launcher script |
| `requirements.txt` | Modify | Add `azure-storage-blob>=12.19.0` |
| `.env.sample` | Modify | Add `STORAGE_ACCOUNT_NAME` and `BLOB_CONTAINER` |
| `.env` | Modify | Add the actual values for both new vars |
| `.gitignore` | Modify | Add `.superpowers/` |
| `tests/test_uploader.py` | Create | Unit tests for `uploader.py` |

---

## Task 1: `uploader.py` — Blob upload helper

**Files:**
- Create: `uploader.py`
- Create: `tests/test_uploader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_uploader.py
import io
from unittest.mock import MagicMock, patch

import pytest

from uploader import upload_blob


@pytest.fixture
def fake_file():
    f = MagicMock()
    f.name = "invoice.pdf"
    f.read.return_value = b"%PDF fake content"
    return f


def test_upload_blob_calls_azure_with_correct_args(fake_file):
    mock_blob_client = MagicMock()
    mock_container_client = MagicMock()
    mock_container_client.get_blob_client.return_value = mock_blob_client
    mock_service_client = MagicMock()
    mock_service_client.get_container_client.return_value = mock_container_client

    with patch("uploader.BlobServiceClient") as MockBSC, \
         patch("uploader.DefaultAzureCredential"):
        MockBSC.return_value = mock_service_client
        result = upload_blob(fake_file, "myaccount", "mycontainer")

    MockBSC.assert_called_once_with(
        account_url="https://myaccount.blob.core.windows.net",
        credential=MockBSC.call_args  # credential is a DefaultAzureCredential instance
    )
    mock_service_client.get_container_client.assert_called_once_with("mycontainer")
    mock_container_client.get_blob_client.assert_called_once_with("invoice.pdf")
    mock_blob_client.upload_blob.assert_called_once_with(fake_file, overwrite=True)
    assert result == "invoice.pdf"


def test_upload_blob_returns_blob_name(fake_file):
    with patch("uploader.BlobServiceClient"), \
         patch("uploader.DefaultAzureCredential"):
        result = upload_blob(fake_file, "acc", "cont")
    assert result == "invoice.pdf"


def test_upload_blob_propagates_errors(fake_file):
    with patch("uploader.BlobServiceClient") as MockBSC, \
         patch("uploader.DefaultAzureCredential"):
        MockBSC.return_value.get_container_client.return_value \
            .get_blob_client.return_value \
            .upload_blob.side_effect = RuntimeError("network error")
        with pytest.raises(RuntimeError, match="network error"):
            upload_blob(fake_file, "acc", "cont")
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python3 -m pytest tests/test_uploader.py -v
```

Expected: `ModuleNotFoundError: No module named 'uploader'`

- [ ] **Step 3: Install azure-storage-blob**

```bash
pip install azure-storage-blob>=12.19.0
```

- [ ] **Step 4: Write `uploader.py`**

```python
"""Azure Blob Storage upload helper."""

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


def upload_blob(file, account_name: str, container_name: str) -> str:
    """Upload a file-like object to Azure Blob Storage.

    Overwrites any existing blob with the same name.
    Returns the blob name on success; raises on failure.
    """
    credential = DefaultAzureCredential()
    service_client = BlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=credential,
    )
    container_client = service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(file.name)
    blob_client.upload_blob(file, overwrite=True)
    return file.name
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python3 -m pytest tests/test_uploader.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Update `requirements.txt`**

Add this line under the RAG agent section:

```
azure-storage-blob>=12.19.0     # Direct blob upload from upload screen
```

- [ ] **Step 7: Update `.env.sample`**

Append these two lines:

```
STORAGE_ACCOUNT_NAME=stinvoiceraginfim0
BLOB_CONTAINER=invoices
```

- [ ] **Step 8: Update `.env`**

Append the same two lines to the local `.env` file (not committed):

```
STORAGE_ACCOUNT_NAME=stinvoiceraginfim0
BLOB_CONTAINER=invoices
```

- [ ] **Step 9: Commit**

```bash
git add uploader.py tests/test_uploader.py requirements.txt .env.sample
git commit -m "feat: add uploader.py — Azure Blob upload helper"
```

---

## Task 2: `pages/2_Chat.py` — move chat screen

**Files:**
- Create: `pages/2_Chat.py`

The chat logic is the entire current `app.py`. It moves verbatim with one addition: a **Back** link in the sidebar that returns to the home screen.

- [ ] **Step 1: Create the pages directory and chat page**

```bash
mkdir -p pages
```

Create `pages/2_Chat.py` with this content (the full current `app.py` with one change — add the Back link at the top of the sidebar block):

```python
"""Invoice Assistant — chat screen."""

import streamlit as st

from agent import build_agent, InvoiceAgent

st.set_page_config(
    page_title="Invoice Assistant · Chat",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    try:
        st.session_state.agent = build_agent()
        st.session_state.agent_error = None
    except EnvironmentError as e:
        st.session_state.agent = None
        st.session_state.agent_error = str(e)


# --- Sidebar -----------------------------------------------------------------

with st.sidebar:
    if st.button("← Home", use_container_width=True):
        st.switch_page("app.py")

    st.title("🧾 Invoice Assistant")
    st.caption("Ask questions about your invoice data in plain English.")
    st.divider()

    if st.session_state.agent_error:
        st.error("Agent not configured")
        st.code(st.session_state.agent_error)
        st.info(
            "Copy `.env.sample` to `.env`, fill in the Phase 2 endpoints "
            "(`cd infra && tofu output`), and sign in with `az login`."
        )
    else:
        agent: InvoiceAgent = st.session_state.agent
        stats = agent.get_stats()
        if not stats:
            st.error("Could not reach the AI Search index.")
            st.info("Check `SEARCH_ENDPOINT` in `.env` and that `az login` has run.")
        else:
            st.success("Connected to AI Search")
            st.subheader("Index")
            st.metric("Invoices indexed", stats.get("total_invoices", "—"))
            currencies = ", ".join(stats.get("currencies") or [])
            if currencies:
                st.caption(f"Currencies: {currencies}")

    st.divider()
    st.subheader("Example questions")
    example_questions = [
        "What is the total amount across all invoices?",
        "Which supplier has the highest total invoice value?",
        "List all invoices in EUR with their amounts.",
        "How many invoices have tax charged?",
        "What is the average invoice amount?",
    ]
    for q in example_questions:
        if st.button(q, use_container_width=True, key=f"ex_{q[:20]}"):
            st.session_state.pending_question = q

    st.divider()
    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent._history = []
        st.rerun()


# --- Main chat area ----------------------------------------------------------

st.header("Invoice Assistant", divider="gray")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("results"):
            with st.expander(
                f"📋 Retrieved invoices ({len(msg['results'])})", expanded=False
            ):
                st.json(msg["results"])

pending = st.session_state.pop("pending_question", None)
user_input = st.chat_input("Ask about your invoices…") or pending

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if st.session_state.agent is None:
        reply = "⚠️ Agent not configured. See the sidebar for setup instructions."
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.stop()

    with st.chat_message("assistant"):
        with st.spinner("Searching invoices…"):
            response = st.session_state.agent.ask(user_input)
        st.markdown(response.answer)
        if response.results:
            with st.expander(
                f"📋 Retrieved invoices ({len(response.results)})", expanded=False
            ):
                st.json(response.results)
        if response.error:
            with st.expander("⚠️ Error details", expanded=False):
                st.code(response.error)

    st.session_state.messages.append({
        "role": "assistant",
        "content": response.answer,
        "results": response.results,
    })
```

- [ ] **Step 2: Verify chat page runs standalone**

```bash
streamlit run pages/2_Chat.py
```

Open http://localhost:8501 — should look identical to the current app. Stop with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add pages/2_Chat.py
git commit -m "feat: move chat UI to pages/2_Chat.py"
```

---

## Task 3: `app.py` — home screen

**Files:**
- Modify: `app.py` (full rewrite)

- [ ] **Step 1: Rewrite `app.py`**

```python
"""Invoice Assistant — home screen / launcher."""

import streamlit as st

from agent import build_agent

st.set_page_config(
    page_title="Invoice Assistant",
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Hide the automatic Streamlit sidebar page nav (we use st.switch_page instead).
st.markdown(
    '<style>[data-testid="stSidebarNav"]{display:none}</style>',
    unsafe_allow_html=True,
)

# Pre-build the agent so session state is warm for the chat page.
if "agent" not in st.session_state:
    try:
        st.session_state.agent = build_agent()
        st.session_state.agent_error = None
    except EnvironmentError as e:
        st.session_state.agent = None
        st.session_state.agent_error = str(e)

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Home screen layout ------------------------------------------------------

st.markdown("<br><br>", unsafe_allow_html=True)
col = st.columns([1, 2, 1])[1]

with col:
    st.markdown("## 🧾 Invoice Assistant")
    st.caption("Extract structured data from invoices and chat with your data.")
    st.markdown("<br>", unsafe_allow_html=True)

    # Index status line
    if st.session_state.agent:
        stats = st.session_state.agent.get_stats()
        count = stats.get("total_invoices")
        if count is not None:
            st.caption(f"📊 {count} invoice{'s' if count != 1 else ''} indexed")
    elif st.session_state.agent_error:
        st.warning("Agent not configured — check your `.env` and run `az login`.")

    st.markdown("<br>", unsafe_allow_html=True)

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("📂 Upload Invoices", use_container_width=True, type="primary"):
            st.switch_page("pages/1_Upload.py")
    with btn_col2:
        if st.button("💬 Chat with Agent", use_container_width=True):
            st.switch_page("pages/2_Chat.py")
```

- [ ] **Step 2: Verify home screen runs**

```bash
streamlit run app.py
```

Open http://localhost:8501 — should show the centred home screen with two buttons. Clicking "Chat with Agent" should navigate to the chat screen. Stop with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: rewrite app.py as home screen launcher"
```

---

## Task 4: `pages/1_Upload.py` — upload screen

**Files:**
- Create: `pages/1_Upload.py`

- [ ] **Step 1: Create `pages/1_Upload.py`**

```python
"""Invoice Assistant — upload screen."""

import csv
import io
import os
import time
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from agent import build_agent
from uploader import upload_blob

load_dotenv()

STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT_NAME", "")
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER", "invoices")
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 60

RESULT_FIELDS = [
    "supplier_name", "invoice_number", "invoice_date", "total_amount",
    "currency", "buyer_name", "subtotal", "tax_amount", "due_date", "po_number",
]

st.set_page_config(
    page_title="Invoice Assistant · Upload",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    '<style>[data-testid="stSidebarNav"]{display:none}</style>',
    unsafe_allow_html=True,
)

# Ensure agent is available in session state for the chat page to reuse.
if "agent" not in st.session_state:
    try:
        st.session_state.agent = build_agent()
        st.session_state.agent_error = None
    except EnvironmentError as e:
        st.session_state.agent = None
        st.session_state.agent_error = str(e)

if "messages" not in st.session_state:
    st.session_state.messages = []


def _poll_for_blob(blob_name: str) -> dict | None:
    """Return the AI Search document for blob_name, or None if not indexed yet."""
    if st.session_state.agent is None:
        return None
    results = st.session_state.agent.search_client.search(
        search_text="*",
        select=["blob_name"] + RESULT_FIELDS,
        top=50,
    )
    for doc in results:
        if doc.get("blob_name") == blob_name:
            return dict(doc)
    return None


def _build_csv(records: list[dict]) -> bytes:
    """Encode extracted invoice records as a UTF-8 CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=RESULT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow({k: (r.get(k) or "") for k in RESULT_FIELDS})
    return buf.getvalue().encode("utf-8")


# --- Page layout -------------------------------------------------------------

if st.button("← Home"):
    st.switch_page("app.py")

st.header("Upload Invoices", divider="gray")
st.caption("Select one or more invoice files. Use Cmd+click (Mac) or Ctrl+click (Windows) to select multiple.")

if not STORAGE_ACCOUNT:
    st.error(
        "STORAGE_ACCOUNT_NAME is not set in your `.env`. "
        "Add it and restart the app."
    )
    st.stop()

uploaded_files = st.file_uploader(
    "Invoice files",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if not uploaded_files:
    st.stop()

if st.button("Upload and process", type="primary"):
    # --- Upload phase --------------------------------------------------------
    st.subheader("Uploading…")
    upload_errors: dict[str, str] = {}

    upload_progress = st.progress(0)
    for i, f in enumerate(uploaded_files):
        try:
            upload_blob(f, STORAGE_ACCOUNT, BLOB_CONTAINER)
        except Exception as e:
            upload_errors[f.name] = str(e)
        upload_progress.progress((i + 1) / len(uploaded_files))

    successful_uploads = [f.name for f in uploaded_files if f.name not in upload_errors]

    if upload_errors:
        for name, err in upload_errors.items():
            st.error(f"❌ {name}: {err}")

    if not successful_uploads:
        st.stop()

    # --- Polling phase -------------------------------------------------------
    st.subheader("Waiting for extraction…")
    st.caption("The Azure Function is processing each file. This usually takes 10–30 seconds.")

    found: dict[str, dict] = {}
    timed_out: list[str] = []
    results_placeholder = st.empty()
    start = time.time()

    while time.time() - start < POLL_TIMEOUT_SECONDS:
        for blob_name in successful_uploads:
            if blob_name not in found and blob_name not in timed_out:
                doc = _poll_for_blob(blob_name)
                if doc:
                    found[blob_name] = doc

        with results_placeholder.container():
            for blob_name in successful_uploads:
                if blob_name in found:
                    doc = found[blob_name]
                    supplier = doc.get("supplier_name") or "—"
                    inv_num = doc.get("invoice_number") or "—"
                    total = doc.get("total_amount")
                    currency = doc.get("currency") or ""
                    amount_str = f"{total:,.2f} {currency}".strip() if total else "—"
                    st.success(f"✓ **{blob_name}** — {supplier} · {inv_num} · {amount_str}")
                elif blob_name in timed_out:
                    st.warning(f"⚠ **{blob_name}** — timed out, may still be processing")
                else:
                    st.info(f"⟳ **{blob_name}** — processing…")

        if len(found) + len(timed_out) == len(successful_uploads):
            break

        # Mark files that have exceeded the timeout
        elapsed = time.time() - start
        if elapsed > POLL_TIMEOUT_SECONDS:
            for blob_name in successful_uploads:
                if blob_name not in found:
                    timed_out.append(blob_name)
            break

        time.sleep(POLL_INTERVAL_SECONDS)

    # Final render after loop
    with results_placeholder.container():
        for blob_name in successful_uploads:
            if blob_name in found:
                doc = found[blob_name]
                supplier = doc.get("supplier_name") or "—"
                inv_num = doc.get("invoice_number") or "—"
                total = doc.get("total_amount")
                currency = doc.get("currency") or ""
                amount_str = f"{total:,.2f} {currency}".strip() if total else "—"
                st.success(f"✓ **{blob_name}** — {supplier} · {inv_num} · {amount_str}")
            else:
                st.warning(f"⚠ **{blob_name}** — timed out, may still be processing")

    # --- Actions -------------------------------------------------------------
    if found:
        completed_records = list(found.values())
        csv_filename = f"invoices_{date.today().isoformat()}.csv"

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            st.download_button(
                label="⬇ Download CSV",
                data=_build_csv(completed_records),
                file_name=csv_filename,
                mime="text/csv",
                use_container_width=True,
            )
        with action_col2:
            if st.button("💬 Chat now →", use_container_width=True, type="primary"):
                st.switch_page("pages/2_Chat.py")
```

- [ ] **Step 2: Verify the upload page loads**

```bash
streamlit run app.py
```

Navigate to Upload via the home screen. The file uploader should appear. Stop with Ctrl+C before attempting an actual upload (that requires the Azure connection).

- [ ] **Step 3: Commit**

```bash
git add pages/1_Upload.py
git commit -m "feat: add upload screen with blob upload, polling, CSV download"
```

---

## Task 5: `launch.command`, gitignore, and README

**Files:**
- Create: `launch.command`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Create `launch.command`**

```bash
#!/bin/bash
# Double-click this file in Finder to open Invoice Assistant.
# First run: right-click → Open (macOS Gatekeeper), then double-click works.
cd "$(dirname "$0")"
open http://localhost:8501
streamlit run app.py
```

Save as `launch.command`.

- [ ] **Step 2: Make it executable**

```bash
chmod +x launch.command
```

- [ ] **Step 3: Add `.superpowers/` to `.gitignore`**

Open `.gitignore` and add this line:

```
.superpowers/
```

- [ ] **Step 4: Update README.md — replace "Run the RAG agent" section**

Find the existing "Run the RAG agent" section and replace it with:

```markdown
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
```

- [ ] **Step 5: Commit everything**

```bash
git add launch.command .gitignore README.md
git commit -m "feat: add launch.command and update README for launcher app"
```

---

## Task 6: End-to-end smoke test

- [ ] **Step 1: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass (existing 9 + new 3 uploader tests = 12 total).

- [ ] **Step 2: Launch the app**

```bash
streamlit run app.py
```

- [ ] **Step 3: Verify home screen**

Open http://localhost:8501. Confirm: centred layout, 🧾 icon, two buttons, index count shown.

- [ ] **Step 4: Navigate to Chat**

Click "Chat with Agent". Confirm: sidebar with Back link, chat input, index stats.

- [ ] **Step 5: Navigate Back**

Click "← Home" in sidebar. Confirm: returns to home screen.

- [ ] **Step 6: Navigate to Upload**

Click "Upload Invoices". Confirm: file uploader appears, "← Home" link visible.

- [ ] **Step 7: Upload a test PDF**

Select one PDF using the file picker and click "Upload and process". Confirm:
- Upload progress bar completes
- Polling spinner appears
- After 10–30 seconds, a green ✓ row appears with supplier name, invoice number, and amount
- "⬇ Download CSV" and "💬 Chat now →" buttons appear

- [ ] **Step 8: Download CSV**

Click "⬇ Download CSV". Confirm a file named `invoices_YYYY-MM-DD.csv` downloads with the correct headers and data.

- [ ] **Step 9: Navigate to Chat via button**

Click "💬 Chat now →". Confirm chat screen opens. Ask "What invoices do we have?" — confirm the newly uploaded invoice appears in the answer.

- [ ] **Step 10: Push to origin**

```bash
git push origin main
```
