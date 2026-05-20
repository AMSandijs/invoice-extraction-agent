# Launcher App — Design

**Date:** 2026-05-20  
**Status:** Approved

---

## 1. Goal

Replace the single-file Streamlit chat app with a three-screen application that a non-technical user can open by double-clicking. The app presents a home screen with two paths: upload invoices to Azure, or chat with the RAG agent about existing invoices.

---

## 2. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| App shell | Streamlit in browser | Minimal extra work; existing UI already Streamlit; launcher script handles double-click |
| Home layout | Centred launcher | Two large buttons front-and-centre; clean demo experience |
| Upload flow | File picker → Blob → poll → show results → Chat button | User sees extraction happen; controls when to switch to chat |
| Post-upload nav | Manual "Chat now →" button | Allows batch uploads before chatting |
| Folder selection | Not supported — multiple file select instead | Browser security prevents folder access; Cmd+click multi-select is equivalent |
| Launcher | `launch.command` shell script | Double-clickable on macOS; no packaging overhead |

---

## 3. Architecture

```
app.py                  ← Home screen (centred launcher)
pages/
  1_Upload.py           ← Upload screen
  2_Chat.py             ← Chat screen (current app.py content, moved here)
launch.command          ← Double-clickable macOS launcher
uploader.py             ← Azure Blob upload helper (new module)
```

The existing `app.py` becomes the home screen. The current chat logic moves to `pages/2_Chat.py` unchanged. `pages/1_Upload.py` is new. `uploader.py` is a thin module that uploads a file-like object to Azure Blob Storage using `DefaultAzureCredential`.

---

## 4. Components

### 4.1 `app.py` — Home screen

Replaces the current chat entry point. Renders:

- Centred layout: `🧾` icon, "Invoice Assistant" title, subtitle
- Two `st.button` calls side by side:
  - **Upload Invoices** → `st.switch_page("pages/1_Upload.py")`
  - **Chat with Agent** → `st.switch_page("pages/2_Chat.py")`
- A small status line at the bottom: index doc count from `agent.get_stats()` (e.g. "5 invoices indexed"). Falls back silently if the agent isn't reachable.

### 4.2 `pages/1_Upload.py` — Upload screen

**Step 1 — File selection**

`st.file_uploader("Select invoice files", type=["pdf","png","jpg","jpeg"], accept_multiple_files=True)`

A note beneath: "Select multiple files with Cmd+click (Mac) or Ctrl+click (Windows)."

**Step 2 — Upload to Azure Blob**

On form submit, each `UploadedFile` is streamed to the `invoices` Blob container via `uploader.upload_blob(file)`. Upload is sequential with a per-file progress indicator. Auth uses `DefaultAzureCredential` (same as the agent — no extra config needed).

**Step 3 — Poll for extraction results**

After upload, a results table is shown with one row per file:

| File | Status | Supplier | Invoice # | Total |
|---|---|---|---|---|
| invoice.pdf | ⟳ Processing… | — | — | — |

The page polls AI Search every 3 seconds (by matching `blob_name`), updating each row when its record appears. Polling stops when all files are found or after 60 seconds (timeout row shown as "⚠ Timed out — may still be processing").

**Step 4 — Download CSV and navigate to chat**

Once at least one file is confirmed indexed:

- A `⬇ Download CSV` button appears, rendered with `st.download_button`. It exports all successfully extracted rows (supplier name, invoice number, date, total, currency, buyer name, subtotal, tax amount, due date, PO number) as a UTF-8 CSV file named `invoices_<YYYY-MM-DD>.csv`. Rows for files that timed out or errored are excluded.
- A `💬 Chat now →` button calls `st.switch_page("pages/2_Chat.py")`.

Both buttons appear side by side. The CSV is built in-memory from the polled AI Search results — no extra API call needed.

A `← Back` link in the top-left returns to the home screen.

### 4.3 `pages/2_Chat.py` — Chat screen

The current `app.py` content moved verbatim. No functional changes. A `← Back` link in the sidebar returns to the home screen.

### 4.4 `uploader.py` — Blob upload helper

```python
def upload_blob(file, account_name, container_name) -> str:
    """Upload a file-like object to Azure Blob Storage. Returns the blob name."""
```

Uses `BlobServiceClient` from `azure-storage-blob` with `DefaultAzureCredential`. The blob name is `file.name`. Overwrites if a blob with the same name exists. Returns the blob name on success, raises on failure.

Storage account name and container name come from environment variables `STORAGE_ACCOUNT_NAME` and `BLOB_CONTAINER` (added to `.env.sample`).

### 4.5 `launch.command` — macOS launcher

```bash
#!/bin/bash
cd "$(dirname "$0")"
open http://localhost:8501
streamlit run app.py
```

`chmod +x launch.command` is required once after cloning. Double-clicking from Finder opens the browser and starts the server in a terminal window. Closing the terminal stops the server.

---

## 5. Configuration

Two new env vars added to `.env.sample` (values already known from `tofu output`):

| Var | Value |
|---|---|
| `STORAGE_ACCOUNT_NAME` | `stinvoiceraginfim0` |
| `BLOB_CONTAINER` | `invoices` |

---

## 6. Dependencies

Add `azure-storage-blob>=12.19.0` to `requirements.txt`. Everything else is already installed.

---

## 7. Error Handling

| Condition | Behaviour |
|---|---|
| No files selected | Submit button disabled / shows hint |
| Upload fails (auth, network) | Per-file error row with message; other files continue |
| Polling times out (60s) | Row shows "⚠ Timed out — may still be processing" |
| Agent unreachable on home screen | Status line omitted silently |
| `az login` session expired | Upload or chat fails with a clear "please run `az login`" error message |

---

## 8. Out of Scope

- Folder selection (browser security prevents it)
- Processing status from the Function directly (we poll AI Search as a proxy)
- Windows packaging (`.exe` or `.msi`) — `launch.command` is macOS-only
- Deleting uploaded invoices from the UI
- Authentication / login screen (single-user local app, auth is via `az login`)
