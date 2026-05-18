"""
Invoice Assistant — Streamlit Chat UI
======================================
Browser-based conversational interface for querying extracted invoice data.

Run with:
    streamlit run app.py
    streamlit run app.py -- --db my_invoices.db   # custom DB path
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

import streamlit as st

from agent import InvoiceAgent


# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Invoice Assistant",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# DB path from CLI args (streamlit passes args after --)
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", default="invoices.db")
    args, _ = parser.parse_known_args()
    return args.db


DB_PATH = get_db_path()


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    try:
        st.session_state.agent = InvoiceAgent(db_path=DB_PATH)
        st.session_state.agent_error = None
    except EnvironmentError as e:
        st.session_state.agent = None
        st.session_state.agent_error = str(e)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🧾 Invoice Assistant")
    st.caption("Ask questions about your extracted invoice data in plain English.")

    st.divider()

    # DB status
    db_exists = Path(DB_PATH).exists()
    if not db_exists:
        st.error(f"Database not found: `{DB_PATH}`")
        st.info(
            "Run the extractor and store steps first:\n\n"
            "```bash\n"
            "python extractor.py ./invoices\n"
            "python store.py extracted_invoices.csv\n"
            "```"
        )
    elif st.session_state.agent_error:
        st.error("API provider not configured")
        st.code(st.session_state.agent_error)
        st.info(
            "Set your API credentials:\n\n"
            "**Azure AI Foundry:**\n"
            "```bash\n"
            "export AZURE_OPENAI_ENDPOINT=...\n"
            "export AZURE_OPENAI_API_KEY=...\n"
            "export AZURE_OPENAI_DEPLOYMENT=gpt-4o\n"
            "```\n\n"
            "**Standard OpenAI:**\n"
            "```bash\n"
            "export OPENAI_API_KEY=sk-...\n"
            "```"
        )
    else:
        st.success(f"Connected: `{DB_PATH}`")

        # DB stats
        agent: InvoiceAgent = st.session_state.agent
        stats = agent.get_stats()

        if stats:
            st.subheader("Database")
            col1, col2 = st.columns(2)
            col1.metric("Invoices", stats.get("total_invoices", "—"))
            col2.metric("Suppliers", stats.get("suppliers", "—"))

            total_val = stats.get("total_value")
            currencies = ", ".join(stats.get("currencies") or [])
            if total_val is not None:
                st.metric("Total Value", f"{total_val:,.2f} ({currencies})")

    st.divider()

    # Example questions
    st.subheader("Example questions")
    example_questions = [
        "What is the total amount across all invoices?",
        "Which supplier has the highest total invoice value?",
        "List all invoices in EUR with their amounts.",
        "How many invoices have tax charged?",
        "Show me all invoices from this month.",
        "What is the average invoice amount?",
    ]
    for q in example_questions:
        if st.button(q, use_container_width=True, key=f"ex_{q[:20]}"):
            st.session_state.pending_question = q

    st.divider()

    # Clear chat
    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent._conversation_history = []
        st.rerun()


# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------

st.header("Invoice Assistant", divider="gray")

# Render existing messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # Show SQL expander for assistant messages that have it
        if msg["role"] == "assistant" and msg.get("sql"):
            with st.expander("🔍 SQL query used", expanded=False):
                st.code(msg["sql"], language="sql")

        # Show raw results if present
        if msg["role"] == "assistant" and msg.get("results"):
            results = msg["results"]
            if len(results) > 0 and len(results) <= 50:
                with st.expander(f"📋 Raw results ({len(results)} row(s))", expanded=False):
                    st.json(results)


# ---------------------------------------------------------------------------
# Handle input — either from chat box or example button
# ---------------------------------------------------------------------------

# Grab pending question from sidebar button press
pending = st.session_state.pop("pending_question", None)
user_input = st.chat_input("Ask about your invoices…") or pending

if user_input:
    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Block if no DB or no agent
    if not db_exists:
        reply = {
            "role": "assistant",
            "content": "⚠️ No invoice database found. Run `extractor.py` and `store.py` first.",
        }
        st.session_state.messages.append(reply)
        with st.chat_message("assistant"):
            st.markdown(reply["content"])
        st.stop()

    if st.session_state.agent is None:
        reply = {
            "role": "assistant",
            "content": "⚠️ API credentials not configured. See the sidebar for instructions.",
        }
        st.session_state.messages.append(reply)
        with st.chat_message("assistant"):
            st.markdown(reply["content"])
        st.stop()

    # Run agent
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            agent: InvoiceAgent = st.session_state.agent
            response = agent.ask(user_input)

        st.markdown(response.answer)

        if response.sql:
            with st.expander("🔍 SQL query used", expanded=False):
                st.code(response.sql, language="sql")

        if response.results and len(response.results) <= 50:
            with st.expander(f"📋 Raw results ({len(response.results)} row(s))", expanded=False):
                st.json(response.results)

        if response.error:
            with st.expander("⚠️ Error details", expanded=False):
                st.code(response.error)

    # Save to history
    st.session_state.messages.append({
        "role": "assistant",
        "content": response.answer,
        "sql": response.sql,
        "results": response.results,
    })
