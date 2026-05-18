"""
Invoice Agent — Text-to-SQL core logic
=======================================
Converts natural language questions into SQL queries, runs them against the
SQLite invoice database, and returns a plain-English answer.

This module is imported by app.py (Streamlit UI).
It can also be used standalone for testing.
"""

import os
import sys
import sqlite3
import json
from dataclasses import dataclass

from openai import OpenAI, AzureOpenAI


# ---------------------------------------------------------------------------
# Schema description sent to the LLM
# ---------------------------------------------------------------------------

DB_SCHEMA = """
Table: invoices
Columns:
  id             INTEGER  - auto-generated row ID
  file           TEXT     - source filename
  method         TEXT     - extraction method used ('text+gpt4o' or 'vision+gpt4o')
  invoice_number TEXT     - invoice reference number
  invoice_date   TEXT     - date invoice was issued (ISO 8601 or as printed)
  supplier_name  TEXT     - company or person who issued the invoice
  buyer_name     TEXT     - company or person billed
  total_amount   REAL     - final payable amount (numeric, no currency symbol)
  currency       TEXT     - 3-letter ISO code or symbol (e.g. 'EUR', 'USD', '$')
  subtotal       REAL     - amount before tax
  tax_amount     REAL     - total tax charged
  tax_rate       TEXT     - tax percentage as string (e.g. '20%')
  due_date       TEXT     - payment due date
  po_number      TEXT     - purchase order number
  payment_terms  TEXT     - e.g. 'Net 30'
  line_items     TEXT     - JSON array of line items
  error          TEXT     - null for successfully extracted rows

Notes:
- NULL means the field was not found on the invoice.
- invoice_date and due_date are stored as strings; use LIKE or date() for filtering.
- total_amount is always a plain number; don't include currency in arithmetic.
- Use LOWER() for case-insensitive text comparisons.
"""

SQL_SYSTEM_PROMPT = f"""You are a SQLite expert. Given a natural language question about invoice data,
write a single, correct SQLite SELECT query that answers it.

{DB_SCHEMA}

Rules:
- Return ONLY the raw SQL query. No explanation, no markdown, no code fences.
- Always use SELECT — never INSERT, UPDATE, DELETE, or DROP.
- Use LOWER() for case-insensitive string matching.
- For aggregations involving total_amount, use ROUND(..., 2).
- If the question is ambiguous, write the most reasonable interpretation.
- If the question cannot be answered with a SQL query (e.g. it is conversational),
  return exactly: NOT_SQL
"""

ANSWER_SYSTEM_PROMPT = """You are a helpful invoice assistant.
Given a user's question, the SQL query that was run, and the query results,
write a clear, concise natural-language answer.

Rules:
- Be direct and specific — include the actual numbers/names from the results.
- If results are empty, say so clearly and suggest why (e.g. no matching supplier).
- Format currency amounts with 2 decimal places.
- Keep the answer to 1-3 sentences unless a longer list is needed.
- Never mention SQL or technical details unless the user asked about them.
"""


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class AgentResponse:
    answer: str
    sql: str | None = None
    results: list | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Client factory (mirrors extractor.py)
# ---------------------------------------------------------------------------

def get_client() -> tuple[OpenAI | AzureOpenAI, str]:
    """Return (client, model_name) based on environment variables."""
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    if azure_endpoint:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY is missing."
            )
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "No API provider configured. Set OPENAI_API_KEY or AZURE_OPENAI_* variables."
            )
        return OpenAI(api_key=api_key), "gpt-4o"


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------

class InvoiceAgent:
    def __init__(self, db_path: str = "invoices.db"):
        self.db_path = db_path
        self.client, self.model = get_client()
        self._conversation_history: list[dict] = []

    # ------------------------------------------------------------------
    # SQL generation
    # ------------------------------------------------------------------

    def _generate_sql(self, question: str) -> str:
        """Ask the LLM to convert a natural language question into SQL."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SQL_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # SQL execution
    # ------------------------------------------------------------------

    def _run_sql(self, sql: str) -> list[dict]:
        """Execute a SELECT query and return rows as a list of dicts."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
            return rows
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------

    def _generate_answer(self, question: str, sql: str, results: list[dict]) -> str:
        """Ask the LLM to turn query results into a natural-language answer."""
        results_text = json.dumps(results, indent=2, default=str) if results else "[]"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"SQL run: {sql}\n\n"
                        f"Results:\n{results_text}"
                    ),
                },
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # Handle a conversational (non-SQL) message
    # ------------------------------------------------------------------

    def _handle_conversational(self, question: str) -> str:
        """Respond to greetings and general questions about the system."""
        self._conversation_history.append({"role": "user", "content": question})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful invoice data assistant. "
                        "You have access to a database of extracted invoice data. "
                        "Users can ask you questions like: 'What is the total amount for invoices from Supplier X?', "
                        "'List all invoices in EUR', 'Which supplier has the highest total?'. "
                        "For conversational messages, respond naturally and briefly. "
                        "Always encourage the user to ask about the invoice data."
                    ),
                },
                *self._conversation_history,
            ],
            temperature=0.5,
        )
        reply = response.choices[0].message.content.strip()
        self._conversation_history.append({"role": "assistant", "content": reply})
        return reply

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def ask(self, question: str) -> AgentResponse:
        """
        Process a user question and return an AgentResponse with:
          - answer: plain-English response
          - sql: the query that was run (or None for conversational messages)
          - results: raw query results (or None)
          - error: error message if something went wrong
        """
        # Step 1: generate SQL
        try:
            sql = self._generate_sql(question)
        except Exception as e:
            return AgentResponse(answer="Sorry, I couldn't process that question.", error=str(e))

        # Conversational fallback
        if sql == "NOT_SQL":
            answer = self._handle_conversational(question)
            return AgentResponse(answer=answer)

        # Guard against non-SELECT statements (safety)
        if not sql.strip().upper().startswith("SELECT"):
            return AgentResponse(
                answer="I can only run read queries on the invoice database.",
                sql=sql,
            )

        # Step 2: run SQL — retry once if it fails
        try:
            results = self._run_sql(sql)
        except sqlite3.Error as e:
            # Retry: send the error back to the LLM for correction
            try:
                fix_prompt = (
                    f"The following SQLite query failed with error: {e}\n\n"
                    f"Query: {sql}\n\n"
                    f"Please fix it."
                )
                sql = self._generate_sql(fix_prompt)
                results = self._run_sql(sql)
            except Exception as e2:
                return AgentResponse(
                    answer="I ran into a database error. Please try rephrasing your question.",
                    sql=sql,
                    error=str(e2),
                )

        # Step 3: generate natural language answer
        try:
            answer = self._generate_answer(question, sql, results)
        except Exception as e:
            return AgentResponse(
                answer="I got the data but couldn't format the answer. Check the raw results below.",
                sql=sql,
                results=results,
                error=str(e),
            )

        return AgentResponse(answer=answer, sql=sql, results=results)

    # ------------------------------------------------------------------
    # DB stats helper (used by Streamlit sidebar)
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return basic stats about the loaded invoice database."""
        try:
            conn = sqlite3.connect(self.db_path)
            stats = {}
            stats["total_invoices"] = conn.execute(
                "SELECT COUNT(*) FROM invoices"
            ).fetchone()[0]
            stats["suppliers"] = conn.execute(
                "SELECT COUNT(DISTINCT supplier_name) FROM invoices WHERE supplier_name IS NOT NULL"
            ).fetchone()[0]
            stats["currencies"] = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT currency FROM invoices WHERE currency IS NOT NULL"
                ).fetchall()
            ]
            stats["total_value"] = conn.execute(
                "SELECT ROUND(SUM(total_amount), 2) FROM invoices WHERE total_amount IS NOT NULL"
            ).fetchone()[0]
            conn.close()
            return stats
        except Exception:
            return {}
