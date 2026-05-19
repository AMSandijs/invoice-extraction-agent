import search_indexer


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
