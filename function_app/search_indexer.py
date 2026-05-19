"""Azure AI Search: index schema, content summary, and document builder."""

from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

# text-embedding-3-large default output dimensionality.
EMBEDDING_DIMENSIONS = 3072

# Numeric fields stored as Edm.Double in the index.
NUMERIC_FIELDS = ("total_amount", "subtotal", "tax_amount")


def build_index(index_name: str) -> SearchIndex:
    """Construct the SearchIndex definition for invoice records."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="supplier_name", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="buyer_name", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="invoice_number", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="po_number", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="currency", type=SearchFieldDataType.String, filterable=True),
        # Dates stored as strings; sort/range correctness requires ISO-8601 (YYYY-MM-DD) format upstream.
        SimpleField(name="invoice_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="due_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="total_amount", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="subtotal", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="tax_amount", type=SearchFieldDataType.Double, filterable=True, sortable=True),
        SimpleField(name="blob_name", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="invoice-hnsw",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="invoice-hnsw-algo")],
        profiles=[
            VectorSearchProfile(
                name="invoice-hnsw",
                algorithm_configuration_name="invoice-hnsw-algo",
            )
        ],
    )
    return SearchIndex(name=index_name, fields=fields, vector_search=vector_search)


def _as_float(value: object) -> "float | None":
    """Coerce a value to float, or None if it is missing/unparseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_content_summary(record: dict) -> str:
    """Synthesize a plain-text paragraph describing an invoice — the text
    that gets embedded for vector search."""
    amount = record.get("total_amount")
    parts = [
        f"Invoice {record.get('invoice_number') or 'n/a'}",
        f"from supplier {record.get('supplier_name') or 'unknown'}",
        f"to buyer {record.get('buyer_name') or 'n/a'}",
        f"dated {record.get('invoice_date') or 'n/a'}",
        f"total {amount if amount is not None else 'n/a'} {record.get('currency') or ''}".strip(),
    ]
    line_items = record.get("line_items")
    if isinstance(line_items, list) and line_items:
        descriptions = ", ".join(
            str(item.get("description", "")).strip()
            for item in line_items
            if isinstance(item, dict) and item.get("description")
        )
        if descriptions:
            parts.append(f"line items: {descriptions}")
    return ". ".join(parts) + "."


def build_search_document(record: dict, content: str, vector: list) -> dict:
    """Map a Cosmos record plus its embedding to an AI Search document."""
    doc = {
        "id": record["id"],
        "supplier_name": record.get("supplier_name"),
        "buyer_name": record.get("buyer_name"),
        "invoice_number": record.get("invoice_number"),
        "po_number": record.get("po_number"),
        "currency": record.get("currency"),
        "invoice_date": record.get("invoice_date"),
        "due_date": record.get("due_date"),
        "blob_name": record.get("blob_name"),
        "content": content,
        "content_vector": vector,
    }
    for field in NUMERIC_FIELDS:
        doc[field] = _as_float(record.get(field))
    return doc
