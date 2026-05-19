from unittest.mock import MagicMock

import function_app

_CONFIG = {
    "gpt_deployment": "gpt-4o",
    "embed_deployment": "text-embedding-3-large",
    "search_index": "invoices-idx",
}


def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _chat_client(json_content):
    client = MagicMock()
    choice = MagicMock()
    choice.message = MagicMock(content=json_content)
    client.chat.completions.create.return_value.choices = [choice]
    client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1])]
    return client


def test_process_blob_success_path():
    function_app._index_ensured = False
    openai_client = _chat_client('{"invoice_number": "INV-1", "supplier_name": "Acme"}')
    cosmos_container = MagicMock()
    search_client = MagicMock()
    index_client = MagicMock()

    record = function_app.process_blob(
        "invoice.png", _png(), _CONFIG,
        openai_client, cosmos_container, search_client, index_client,
    )

    assert record["status"] == "extracted"
    index_client.create_or_update_index.assert_called_once()
    cosmos_container.upsert_item.assert_called_once()
    search_client.upload_documents.assert_called_once()


def test_process_blob_extraction_failure_path():
    function_app._index_ensured = False
    cosmos_container = MagicMock()
    search_client = MagicMock()
    index_client = MagicMock()

    record = function_app.process_blob(
        "notes.txt", b"not an invoice", _CONFIG,
        MagicMock(), cosmos_container, search_client, index_client,
    )

    assert record["status"] == "error"
    assert "Unsupported" in record["error"]
    cosmos_container.upsert_item.assert_called_once()
    search_client.upload_documents.assert_not_called()
