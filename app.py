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
