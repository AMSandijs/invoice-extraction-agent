"""SQLite storage for local mode — replaces Azure Cosmos DB."""

import os
import sqlite3
from contextlib import contextmanager

_DB_PATH = os.environ.get("LOCAL_DB_PATH") or os.path.join(
    os.path.dirname(__file__), "data", "invoices.db"
)
# _DB_PATH is relative to the module file, not the cwd — data/ always lives in the repo root.

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

# For :memory: databases, sqlite3 creates a fresh DB per connection, so we
# keep a single shared connection alive for the lifetime of the process.
_MEMORY_CONN: sqlite3.Connection | None = None


def _get_memory_conn() -> sqlite3.Connection:
    global _MEMORY_CONN
    if _MEMORY_CONN is None:
        _MEMORY_CONN = sqlite3.connect(":memory:", check_same_thread=False)
        _MEMORY_CONN.row_factory = sqlite3.Row
        _MEMORY_CONN.execute(_SCHEMA)
        _MEMORY_CONN.commit()
    return _MEMORY_CONN


@contextmanager
def _conn():
    if _DB_PATH == ":memory:":
        yield _get_memory_conn()
        return
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
