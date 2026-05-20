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
