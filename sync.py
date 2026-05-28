"""Cosmos DB / AI Search admin operations.

Called by admin buttons in app.py and by scripts/rebuild_search_index.py.
"""

import csv
import io
import os
import sys

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI

from csv_safe import sanitize_cell

# Allow importing search_indexer from the function_app package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "function_app"))
import search_indexer  # noqa: E402  (import after path manipulation)

CSV_FIELDS = [
    "blob_name", "supplier_name", "supplier_name_en", "invoice_number",
    "invoice_date", "total_amount", "currency", "buyer_name", "buyer_name_en",
    "subtotal", "tax_amount", "tax_rate", "due_date", "po_number", "payment_terms",
]


def rebuild(
    cosmos_endpoint: str,
    cosmos_database: str,
    cosmos_container: str,
    search_endpoint: str,
    search_index: str,
    openai_endpoint: str,
    openai_api_version: str,
    embed_deployment: str,
    progress_callback=None,
) -> dict:
    """Delete and rebuild the AI Search index from all extracted Cosmos records.

    progress_callback(message: str, fraction: float) is called at each step
    if provided — use it to drive a Streamlit progress bar.

    Returns {"indexed": int, "errors": int}.
    """
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=openai_api_version,
    )
    cosmos_container_client = (
        CosmosClient(cosmos_endpoint, credential=credential)
        .get_database_client(cosmos_database)
        .get_container_client(cosmos_container)
    )
    search_client = SearchClient(search_endpoint, search_index, credential=credential)
    index_client = SearchIndexClient(search_endpoint, credential=credential)

    if progress_callback:
        progress_callback("Recreating Search index…", 0.0)

    try:
        index_client.delete_index(search_index)
    except Exception:
        pass
    search_indexer.ensure_index(index_client, search_index)

    if progress_callback:
        progress_callback("Reading records from Cosmos DB…", 0.1)

    records = list(cosmos_container_client.query_items(
        "SELECT * FROM c WHERE c.status = 'extracted'"
        " AND (NOT IS_DEFINED(c.deleted) OR c.deleted != true)",
        enable_cross_partition_query=True,
    ))

    indexed, errors = 0, 0
    total = len(records)

    for i, record in enumerate(records, 1):
        if progress_callback:
            progress_callback(
                f"Indexing {record.get('blob_name', record['id'])} ({i}/{total})…",
                0.1 + 0.9 * (i / max(total, 1)),
            )
        try:
            search_indexer.index_record(
                search_client, openai_client, embed_deployment, record
            )
            indexed += 1
        except Exception:
            errors += 1

    return {"indexed": indexed, "errors": errors}


def clear_all(
    cosmos_endpoint: str,
    cosmos_database: str,
    cosmos_container: str,
    search_endpoint: str,
    search_index: str,
    progress_callback=None,
) -> dict:
    """Delete every invoice record from Cosmos DB and reset the Search index.

    Returns {"deleted": int}.
    """
    credential = DefaultAzureCredential()
    cosmos_container_client = (
        CosmosClient(cosmos_endpoint, credential=credential)
        .get_database_client(cosmos_database)
        .get_container_client(cosmos_container)
    )
    index_client = SearchIndexClient(search_endpoint, credential=credential)

    if progress_callback:
        progress_callback("Reading records from Cosmos DB…", 0.0)

    items = list(cosmos_container_client.query_items(
        "SELECT c.id, c.supplier_name, c.blob_name FROM c",
        enable_cross_partition_query=True,
    ))
    total = len(items)

    for i, item in enumerate(items, 1):
        if progress_callback:
            progress_callback(
                f"Deleting {item.get('blob_name', item['id'])} ({i}/{total})…",
                0.1 + 0.8 * (i / max(total, 1)),
            )
        cosmos_container_client.delete_item(
            item=item["id"],
            partition_key=item["supplier_name"],
        )

    if progress_callback:
        progress_callback("Resetting AI Search index…", 0.9)

    try:
        index_client.delete_index(search_index)
    except Exception:
        pass
    search_indexer.ensure_index(index_client, search_index)

    return {"deleted": total}


def export_csv(
    cosmos_endpoint: str,
    cosmos_database: str,
    cosmos_container: str,
) -> bytes:
    """Return all extracted Cosmos DB records as UTF-8 CSV bytes."""
    credential = DefaultAzureCredential()
    cosmos_container_client = (
        CosmosClient(cosmos_endpoint, credential=credential)
        .get_database_client(cosmos_database)
        .get_container_client(cosmos_container)
    )

    records = list(cosmos_container_client.query_items(
        "SELECT * FROM c WHERE c.status = 'extracted'"
        " AND (NOT IS_DEFINED(c.deleted) OR c.deleted != true)",
        enable_cross_partition_query=True,
    ))

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow({k: sanitize_cell(r.get(k)) for k in CSV_FIELDS})
    return buf.getvalue().encode("utf-8")
