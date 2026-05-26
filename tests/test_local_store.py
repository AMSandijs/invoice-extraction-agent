import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point at a temp DB so tests don't touch ./data/invoices.db
os.environ["LOCAL_DB_PATH"] = ":memory:"

import local_store


@pytest.fixture(autouse=True)
def _clean_db():
    local_store.delete_all()


SAMPLE = {
    "id": "abc123",
    "blob_name": "test.pdf",
    "supplier_name": "Acme Corp",
    "supplier_name_en": "Acme Corp",
    "invoice_number": "INV-001",
    "invoice_date": "2024-01-15",
    "total_amount": 1234.56,
    "currency": "USD",
    "buyer_name": "Buyer Ltd",
    "buyer_name_en": "Buyer Ltd",
    "subtotal": 1000.0,
    "tax_amount": 234.56,
    "due_date": "2024-02-15",
    "po_number": "PO-99",
    "content": "Invoice INV-001 from Acme Corp to Buyer Ltd.",
}


def test_upsert_and_count():
    local_store.upsert_invoice(SAMPLE)
    assert local_store.get_invoice_count() == 1


def test_get_all_returns_record():
    local_store.upsert_invoice(SAMPLE)
    rows = local_store.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["supplier_name"] == "Acme Corp"


def test_currencies():
    local_store.upsert_invoice(SAMPLE)
    assert "USD" in local_store.get_currencies()


def test_get_by_blob():
    local_store.upsert_invoice(SAMPLE)
    row = local_store.get_invoice_by_blob("test.pdf")
    assert row is not None
    assert row["invoice_number"] == "INV-001"


def test_upsert_is_idempotent():
    local_store.upsert_invoice(SAMPLE)
    local_store.upsert_invoice(SAMPLE)
    assert local_store.get_invoice_count() == 1


def test_delete_all():
    local_store.upsert_invoice(SAMPLE)
    deleted = local_store.delete_all()
    assert deleted == 1
    assert local_store.get_invoice_count() == 0
