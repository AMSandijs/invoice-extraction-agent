"""Assemble invoice records and persist them to Cosmos DB."""

import hashlib
from datetime import datetime, timezone

# Invoice fields carried from extraction into the stored record.
INVOICE_FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "supplier_name_en",
    "buyer_name",
    "buyer_name_en",
    "total_amount",
    "currency",
    "subtotal",
    "tax_amount",
    "tax_rate",
    "due_date",
    "po_number",
    "payment_terms",
    "line_items",
]


def record_id(blob_name: str) -> str:
    """A deterministic document id, so re-uploading a file upserts cleanly."""
    return hashlib.sha256(blob_name.encode("utf-8")).hexdigest()


def build_record(
    blob_name: str,
    extracted: dict | None = None,
    method: str | None = None,
    status: str = "extracted",
    error: str | None = None,
) -> dict:
    """Build a Cosmos document from extracted fields (or an error result).

    `supplier_name` is the container partition key, so it is never null —
    it falls back to 'unknown'.
    """
    extracted = extracted or {}
    record = {field: extracted.get(field) for field in INVOICE_FIELDS}
    record["id"] = record_id(blob_name)
    record["blob_name"] = blob_name
    record["method"] = method
    record["supplier_name"] = record.get("supplier_name") or "unknown"
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    record["status"] = status
    record["error"] = error
    return record


def upsert(container, record: dict) -> None:
    """Upsert a record into the Cosmos container."""
    # Return value (upserted document with _etag/_ts) is intentionally ignored.
    container.upsert_item(record)


def soft_delete(container, blob_name: str) -> None:
    """Mark a record as deleted.

    Sets deleted=True on the existing document so the change feed trigger
    removes it from AI Search. Silently does nothing if the record is not found.
    """
    doc_id = record_id(blob_name)
    items = list(container.query_items(
        f"SELECT * FROM c WHERE c.id = '{doc_id}'",
        enable_cross_partition_query=True,
    ))
    if not items:
        return
    doc = items[0]
    doc["deleted"] = True
    container.upsert_item(doc)
