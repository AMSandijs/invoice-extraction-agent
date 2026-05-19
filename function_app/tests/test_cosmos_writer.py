from unittest.mock import MagicMock

import cosmos_writer


def test_record_id_is_deterministic():
    assert cosmos_writer.record_id("a.pdf") == cosmos_writer.record_id("a.pdf")
    assert cosmos_writer.record_id("a.pdf") != cosmos_writer.record_id("b.pdf")


def test_build_record_extracted():
    extracted = {"invoice_number": "INV-9", "supplier_name": "Acme", "total_amount": 100.0}
    record = cosmos_writer.build_record("inv.pdf", extracted=extracted, method="text+gpt4o")
    assert record["id"] == cosmos_writer.record_id("inv.pdf")
    assert record["blob_name"] == "inv.pdf"
    assert record["invoice_number"] == "INV-9"
    assert record["supplier_name"] == "Acme"
    assert record["method"] == "text+gpt4o"
    assert record["status"] == "extracted"
    assert record["error"] is None
    assert record["processed_at"]  # ISO timestamp present


def test_build_record_missing_supplier_defaults_to_unknown():
    record = cosmos_writer.build_record("inv.pdf", extracted={}, method="text+gpt4o")
    assert record["supplier_name"] == "unknown"


def test_build_record_error():
    record = cosmos_writer.build_record("bad.pdf", status="error", error="boom")
    assert record["status"] == "error"
    assert record["error"] == "boom"
    assert record["supplier_name"] == "unknown"
    assert record["invoice_number"] is None


def test_upsert_calls_container():
    container = MagicMock()
    record = {"id": "x"}
    cosmos_writer.upsert(container, record)
    container.upsert_item.assert_called_once_with(record)
