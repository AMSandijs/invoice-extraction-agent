"""
Invoice Store — CSV to SQLite
==============================
Loads the CSV produced by extractor.py into a local SQLite database.
Run this once after extraction, then use app.py to query the data.

Usage:
    python store.py extracted_invoices.csv
    python store.py extracted_invoices.csv --db invoices.db   # custom DB path
"""

import sys
import json
import argparse
import sqlite3
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file            TEXT,
    method          TEXT,
    invoice_number  TEXT,
    invoice_date    TEXT,
    supplier_name   TEXT,
    buyer_name      TEXT,
    total_amount    REAL,
    currency        TEXT,
    subtotal        REAL,
    tax_amount      REAL,
    tax_rate        TEXT,
    due_date        TEXT,
    po_number       TEXT,
    payment_terms   TEXT,
    line_items      TEXT,
    error           TEXT
);
"""

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_csv_to_db(csv_path: str, db_path: str = "invoices.db") -> int:
    """
    Read a CSV file produced by extractor.py and upsert all rows into the
    SQLite database at db_path.  Returns the number of rows inserted.
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        sys.exit(f"[ERROR] CSV file not found: {csv_path}")

    df = pd.read_csv(csv_file)

    # Only keep rows that were successfully extracted (no error)
    failed = df[df["error"].notna() & (df["error"] != "")]
    df = df[df["error"].isna() | (df["error"] == "")]

    if failed.shape[0]:
        print(f"[WARN] Skipping {failed.shape[0]} row(s) with extraction errors:")
        for _, row in failed.iterrows():
            print(f"       {row['file']}: {row['error']}")

    if df.empty:
        print("[WARN] No valid rows to insert.")
        return 0

    # Coerce numeric columns — pandas may read them as objects
    for col in ("total_amount", "subtotal", "tax_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(CREATE_TABLE_SQL)

        # Remove existing rows for the same filenames so re-running is safe
        existing_files = tuple(df["file"].dropna().unique())
        if existing_files:
            placeholders = ",".join("?" * len(existing_files))
            conn.execute(
                f"DELETE FROM invoices WHERE file IN ({placeholders})",
                existing_files,
            )

        df.to_sql("invoices", conn, if_exists="append", index=False)
        conn.commit()
        n = len(df)
        print(f"[OK] Loaded {n} invoice(s) into '{db_path}'")

        # Quick summary
        summary = conn.execute(
            "SELECT COUNT(*), SUM(total_amount), currency FROM invoices GROUP BY currency"
        ).fetchall()
        print("\n  Summary by currency:")
        for row in summary:
            count, total, currency = row
            print(f"    {currency or '?':5s}  {count:3d} invoice(s)  total: {total:,.2f}")

    finally:
        conn.close()

    return n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load extracted invoice CSV into a SQLite database."
    )
    parser.add_argument("csv", help="Path to the extracted_invoices.csv from extractor.py")
    parser.add_argument(
        "--db", default="invoices.db", help="SQLite database file (default: invoices.db)"
    )
    args = parser.parse_args()
    load_csv_to_db(args.csv, args.db)


if __name__ == "__main__":
    main()
