"""Invoice Assistant — home screen / launcher."""

import os

import streamlit as st
from dotenv import load_dotenv

from agent import build_agent
from csv_safe import sanitize_cell

load_dotenv()

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

    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("⚙ Admin"):
        if os.environ.get("SEARCH_ENDPOINT"):
            # ---- Cloud admin ----
            from sync import clear_all, export_csv, rebuild

            st.caption("**Sync** — rebuild the AI Search index from Cosmos DB if the count looks wrong.")
            if st.button("🔄 Sync index from Cosmos DB", use_container_width=True):
                progress_bar = st.progress(0.0)
                status = st.empty()

                def _update(msg: str, fraction: float) -> None:
                    status.caption(msg)
                    progress_bar.progress(fraction)

                try:
                    result = rebuild(
                        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
                        cosmos_database=os.environ["COSMOS_DATABASE"],
                        cosmos_container=os.environ["COSMOS_CONTAINER"],
                        search_endpoint=os.environ["SEARCH_ENDPOINT"],
                        search_index=os.environ["SEARCH_INDEX"],
                        openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                        openai_api_version=os.environ["AZURE_OPENAI_API_VERSION"],
                        embed_deployment=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
                        progress_callback=_update,
                    )
                    progress_bar.progress(1.0)
                    status.success(
                        f"Sync complete — {result['indexed']} indexed"
                        + (f", {result['errors']} error(s)" if result["errors"] else "")
                    )
                    st.session_state.pop("agent", None)
                    st.session_state.pop("admin_csv", None)
                    st.rerun()
                except Exception as exc:
                    status.error(f"Sync failed: {exc}")

            st.divider()

            st.caption("**Export** — download all stored invoices as a CSV file.")
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
                    try:
                        with st.spinner("Reading from Cosmos DB…"):
                            st.session_state["admin_csv"] = export_csv(
                                cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
                                cosmos_database=os.environ["COSMOS_DATABASE"],
                                cosmos_container=os.environ["COSMOS_CONTAINER"],
                            )
                    except Exception as exc:
                        st.error(f"Export failed: {exc}")
                    st.rerun()

            st.divider()

            st.caption("**Clear** — permanently delete all invoices from Cosmos DB and reset the Search index.")
            confirm = st.checkbox("I understand this will permanently delete all stored invoices")
            if st.button("🗑 Clear all invoices", disabled=not confirm, use_container_width=True):
                progress_bar2 = st.progress(0.0)
                status2 = st.empty()

                def _update2(msg: str, fraction: float) -> None:
                    status2.caption(msg)
                    progress_bar2.progress(fraction)

                try:
                    result2 = clear_all(
                        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
                        cosmos_database=os.environ["COSMOS_DATABASE"],
                        cosmos_container=os.environ["COSMOS_CONTAINER"],
                        search_endpoint=os.environ["SEARCH_ENDPOINT"],
                        search_index=os.environ["SEARCH_INDEX"],
                        progress_callback=_update2,
                    )
                    progress_bar2.progress(1.0)
                    status2.success(f"Cleared {result2['deleted']} invoice(s).")
                    st.session_state.pop("agent", None)
                    st.session_state.pop("admin_csv", None)
                    st.rerun()
                except Exception as exc:
                    status2.error(f"Clear failed: {exc}")

        else:
            # ---- Local admin ----
            import local_store
            from datetime import date as _date

            st.caption("**Export** — download all locally stored invoices as CSV.")
            if st.session_state.get("admin_csv"):
                st.download_button(
                    label="⬇ Export CSV",
                    data=st.session_state["admin_csv"],
                    file_name=f"invoices_{_date.today().isoformat()}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                if st.button("⬇ Export CSV", use_container_width=True):
                    import csv, io as _io
                    records = local_store.get_all_invoices()
                    fields = [
                        "blob_name", "supplier_name", "invoice_number", "invoice_date",
                        "total_amount", "currency", "buyer_name", "subtotal",
                        "tax_amount", "due_date", "po_number",
                    ]
                    buf = _io.StringIO()
                    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    for r in records:
                        writer.writerow({k: sanitize_cell(r.get(k)) for k in fields})
                    st.session_state["admin_csv"] = buf.getvalue().encode("utf-8")
                    st.rerun()

            st.divider()

            st.caption("**Clear** — permanently delete all locally stored invoices.")
            confirm = st.checkbox("I understand this will permanently delete all stored invoices")
            if st.button("🗑 Clear all invoices", disabled=not confirm, use_container_width=True):
                deleted = local_store.delete_all()
                if st.session_state.get("agent"):
                    try:
                        col = st.session_state.agent._col
                        col.delete(where={"blob_name": {"$ne": ""}})
                    except Exception:
                        pass
                st.success(f"Cleared {deleted} invoice(s).")
                st.session_state.pop("agent", None)
                st.session_state.pop("admin_csv", None)
                st.rerun()
