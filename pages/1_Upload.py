"""Invoice Assistant — upload screen."""

import csv
import hashlib
import io
import os
import sys
import tempfile
import time
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from agent import build_agent
from uploader import upload_blob

try:
    from analytics import track
except ImportError:
    def track(event, props=None): pass

load_dotenv()

STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT_NAME", "")
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER", "invoices")
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 180
IS_LOCAL_MODE = not STORAGE_ACCOUNT

RESULT_FIELDS = [
    "supplier_name", "supplier_name_en", "invoice_number", "invoice_date",
    "total_amount", "currency", "buyer_name", "buyer_name_en",
    "subtotal", "tax_amount", "due_date", "po_number",
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

if "agent" not in st.session_state:
    try:
        st.session_state.agent = build_agent()
        st.session_state.agent_error = None
    except EnvironmentError as e:
        st.session_state.agent = None
        st.session_state.agent_error = str(e)

if "messages" not in st.session_state:
    st.session_state.messages = []


def _poll_for_blobs(pending: list[str]) -> dict[str, dict]:
    """Scan AI Search once and return all docs whose blob_name is in pending."""
    if st.session_state.agent is None:
        return {}
    results = st.session_state.agent.search_client.search(
        search_text="*",
        select=["blob_name"] + RESULT_FIELDS,
        top=50,
    )
    return {
        doc["blob_name"]: dict(doc)
        for doc in results
        if doc.get("blob_name") in pending
    }


def _build_csv(records: list[dict]) -> bytes:
    """Encode extracted invoice records as a UTF-8 CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=RESULT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow({k: (r.get(k) or "") for k in RESULT_FIELDS})
    return buf.getvalue().encode("utf-8")


def _run_local_extraction(uploaded_files) -> None:
    """Extract invoices inline — no blob upload, no polling."""
    if st.session_state.agent is None:
        st.error("Agent not configured. Check your .env.")
        return

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from extractor import get_client, process_file as _extract_file

    st.subheader("Extracting…")
    client, model = get_client()
    progress = st.progress(0)
    results = []

    for i, f in enumerate(uploaded_files):
        suffix = os.path.splitext(f.name)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name

        try:
            with st.spinner(f"Extracting {f.name}…"):
                record = _extract_file(client, tmp_path, model)
        finally:
            os.unlink(tmp_path)

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
            "supplier_name_en": record.get("supplier_name"),
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
        track("invoices_uploaded", {"count": len(results), "files": ", ".join(r["blob_name"] for r in results)})
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


def _run_cloud_upload(uploaded_files) -> None:
    """Upload to Azure Blob Storage and poll AI Search for extraction results."""
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
    if successful_uploads:
        track("invoices_uploaded", {"count": len(successful_uploads), "files": ", ".join(successful_uploads)})

    if upload_errors:
        for name, err in upload_errors.items():
            st.error(f"❌ {name}: {err}")

    if not successful_uploads:
        st.stop()

    st.subheader("Waiting for extraction…")
    st.caption("The Azure Function is processing each file. This usually takes 10–30 seconds.")

    found: dict[str, dict] = {}
    timed_out: set[str] = set()
    results_placeholder = st.empty()
    start = time.time()

    while time.time() - start < POLL_TIMEOUT_SECONDS:
        pending = [b for b in successful_uploads if b not in found]
        if pending:
            newly_found = _poll_for_blobs(pending)
            found.update(newly_found)

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

        time.sleep(POLL_INTERVAL_SECONDS)

    for blob_name in successful_uploads:
        if blob_name not in found:
            timed_out.add(blob_name)

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


# --- Page layout -------------------------------------------------------------

if "tracked_upload" not in st.session_state:
    track("page_view", {"page": "upload"})
    st.session_state.tracked_upload = True

if st.button("← Home"):
    st.switch_page("app.py")

st.header("Upload Invoices", divider="gray")
st.caption("Select one or more invoice files. Use Cmd+click (Mac) or Ctrl+click (Windows) to select multiple.")

if not IS_LOCAL_MODE and not STORAGE_ACCOUNT:
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
    if IS_LOCAL_MODE:
        _run_local_extraction(uploaded_files)
    else:
        _run_cloud_upload(uploaded_files)
