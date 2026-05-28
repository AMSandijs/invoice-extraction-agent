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
        agent = st.session_state.agent
        stats = agent.get_stats()
        if not stats:
            st.error("Could not reach the invoice index.")
            st.info("Check your `.env` configuration and authentication.")
        else:
            st.success("Connected to invoice index")
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

def _md(text: str) -> None:
    """Render markdown with dollar signs escaped to prevent Streamlit LaTeX mode."""
    st.markdown(text.replace("$", r"\$"))


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        _md(msg["content"])
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
        _md(response.answer)
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
