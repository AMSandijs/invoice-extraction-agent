"""Azure Function: process_invoice — blob-triggered invoice ingestion.

A new blob in the `invoices/` container triggers extraction with GPT-4o,
an upsert to Cosmos DB, and a push to the Azure AI Search index.
"""

import logging
import os
import threading

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI

import cosmos_writer
import extraction
import search_indexer

app = func.FunctionApp()

# Ensures the Search index is created once per worker process (cold start).
_index_ensured = False
_index_lock = threading.Lock()


def load_config() -> dict:
    """Read configuration from Function App settings."""
    return {
        "openai_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
        "openai_api_version": os.environ["AZURE_OPENAI_API_VERSION"],
        "gpt_deployment": os.environ["AZURE_OPENAI_GPT_DEPLOYMENT"],
        "embed_deployment": os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        "cosmos_endpoint": os.environ["COSMOS_ENDPOINT"],
        "cosmos_database": os.environ["COSMOS_DATABASE"],
        "cosmos_container": os.environ["COSMOS_CONTAINER"],
        "search_endpoint": os.environ["SEARCH_ENDPOINT"],
        "search_index": os.environ["SEARCH_INDEX"],
    }


def build_clients(config: dict):
    """Construct Azure SDK clients using the Function's managed identity.

    Returns (openai_client, cosmos_container, search_client, index_client).
    """
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    openai_client = AzureOpenAI(
        azure_endpoint=config["openai_endpoint"],
        azure_ad_token_provider=token_provider,
        api_version=config["openai_api_version"],
    )
    cosmos_container = (
        CosmosClient(config["cosmos_endpoint"], credential=credential)
        .get_database_client(config["cosmos_database"])
        .get_container_client(config["cosmos_container"])
    )
    search_client = SearchClient(
        config["search_endpoint"], config["search_index"], credential=credential
    )
    index_client = SearchIndexClient(config["search_endpoint"], credential=credential)
    return openai_client, cosmos_container, search_client, index_client


def process_blob(blob_name, data, config, openai_client, cosmos_container,
                 search_client, index_client) -> dict:
    """Core ingestion logic. Returns the record written to Cosmos.

    Extraction failures are caught and stored as error records; transient
    infrastructure errors propagate so the Functions host retries the blob.
    """
    global _index_ensured
    with _index_lock:
        if not _index_ensured:
            search_indexer.ensure_index(index_client, config["search_index"])
            _index_ensured = True

    try:
        extracted, method = extraction.extract(
            openai_client, config["gpt_deployment"], blob_name, data
        )
    except Exception as exc:  # extraction failure — record it, do not index
        logging.exception("Extraction failed for %s", blob_name)
        record = cosmos_writer.build_record(blob_name, status="error", error=str(exc))
        cosmos_writer.upsert(cosmos_container, record)
        return record

    record = cosmos_writer.build_record(blob_name, extracted=extracted, method=method)
    cosmos_writer.upsert(cosmos_container, record)
    search_indexer.index_record(
        search_client, openai_client, config["embed_deployment"], record
    )
    logging.info("Indexed invoice %s", blob_name)
    return record


@app.cosmos_db_trigger(
    arg_name="documents",
    database_name="%COSMOS_DATABASE%",
    container_name="%COSMOS_CONTAINER%",
    connection="COSMOS_CHANGE_FEED",
    lease_database_name="%COSMOS_DATABASE%",
    lease_container_name="leases",
    create_lease_container_if_not_exists=True,
)
def sync_search(documents: func.DocumentList) -> None:
    """Change feed trigger: removes soft-deleted records from AI Search.

    process_invoice already pushes to Search on creation, so this function
    only handles soft-deletes (deleted=True) to avoid double embedding calls.
    """
    config = load_config()
    _, _, search_client, _ = build_clients(config)

    to_delete = [
        {"id": dict(doc)["id"]}
        for doc in documents
        if dict(doc).get("deleted") and dict(doc).get("id")
    ]

    if to_delete:
        search_client.delete_documents(documents=to_delete)
        logging.info("Removed %d soft-deleted doc(s) from Search", len(to_delete))


@app.blob_trigger(arg_name="blob", path="invoices/{name}", connection="AzureWebJobsStorage")
def process_invoice(blob: func.InputStream):
    """Blob trigger entrypoint for the `invoices/` container."""
    blob_name = blob.name.split("/", 1)[-1]
    logging.info("process_invoice triggered for %s", blob_name)
    config = load_config()
    clients = build_clients(config)
    process_blob(blob_name, blob.read(), config, *clients)
