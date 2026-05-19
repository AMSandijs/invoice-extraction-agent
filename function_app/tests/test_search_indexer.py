import search_indexer
from unittest.mock import MagicMock


def test_build_index_has_key_and_vector_field():
    index = search_indexer.build_index("invoices-idx")
    assert index.name == "invoices-idx"
    fields = {f.name: f for f in index.fields}
    assert fields["id"].key is True
    assert "content" in fields
    vector = fields["content_vector"]
    assert vector.vector_search_dimensions == search_indexer.EMBEDDING_DIMENSIONS


def test_build_content_summary_includes_core_fields():
    record = {
        "invoice_number": "INV-7",
        "supplier_name": "Acme",
        "buyer_name": "Globex",
        "invoice_date": "2024-03-01",
        "total_amount": 500.0,
        "currency": "EUR",
        "line_items": [{"description": "Widget"}],
    }
    summary = search_indexer.build_content_summary(record)
    assert "INV-7" in summary
    assert "Acme" in summary
    assert "Widget" in summary


def test_build_content_summary_zero_amount_not_suppressed():
    record = {
        "invoice_number": "INV-0",
        "supplier_name": "Acme",
        "total_amount": 0.0,
        "currency": "EUR",
    }
    summary = search_indexer.build_content_summary(record)
    assert "0.0" in summary
    assert "n/a" not in summary.split("total")[1]


def test_build_search_document_maps_fields_and_floats():
    record = {
        "id": "abc",
        "supplier_name": "Acme",
        "buyer_name": "Globex",
        "invoice_number": "INV-7",
        "po_number": None,
        "currency": "EUR",
        "invoice_date": "2024-03-01",
        "due_date": None,
        "blob_name": "inv.pdf",
        "total_amount": "500.0",
        "subtotal": None,
        "tax_amount": "not-a-number",
    }
    doc = search_indexer.build_search_document(record, "summary text", [0.1, 0.2])
    assert doc["id"] == "abc"
    assert doc["content"] == "summary text"
    assert doc["content_vector"] == [0.1, 0.2]
    assert doc["total_amount"] == 500.0
    assert doc["subtotal"] is None
    assert doc["tax_amount"] is None  # unparseable value coerced to None


def test_ensure_index_creates_or_updates():
    index_client = MagicMock()
    search_indexer.ensure_index(index_client, "invoices-idx")
    index_client.create_or_update_index.assert_called_once()
    created = index_client.create_or_update_index.call_args[0][0]
    assert created.name == "invoices-idx"


def test_embed_returns_vector():
    openai_client = MagicMock()
    openai_client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2])]
    vector = search_indexer.embed(openai_client, "text-embedding-3-large", "hello")
    assert vector == [0.1, 0.2]
    openai_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-large", input="hello"
    )


def test_index_record_embeds_and_uploads():
    search_client = MagicMock()
    openai_client = MagicMock()
    openai_client.embeddings.create.return_value.data = [MagicMock(embedding=[0.3])]
    record = {"id": "abc", "supplier_name": "Acme", "invoice_number": "INV-1"}

    search_indexer.index_record(search_client, openai_client, "text-embedding-3-large", record)

    search_client.upload_documents.assert_called_once()
    uploaded = search_client.upload_documents.call_args.kwargs["documents"][0]
    assert uploaded["id"] == "abc"
    assert uploaded["content_vector"] == [0.3]
    assert uploaded["content"]  # summary populated
