import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["LOCAL_DB_PATH"] = ":memory:"
os.environ["LOCAL_CHROMA_PATH"] = ":memory:"

import local_store

SAMPLE_RECORD = {
    "id": "def456",
    "blob_name": "invoice.pdf",
    "supplier_name": "Test Supplier",
    "supplier_name_en": "Test Supplier",
    "invoice_number": "INV-999",
    "invoice_date": "2024-06-01",
    "total_amount": 500.0,
    "currency": "EUR",
    "buyer_name": "Buyer Co",
    "buyer_name_en": "Buyer Co",
    "subtotal": 413.22,
    "tax_amount": 86.78,
    "due_date": None,
    "po_number": None,
    "content": "Invoice INV-999 from Test Supplier to Buyer Co dated 2024-06-01 total 500.0 EUR.",
}


class _FakeEmbedding:
    def create(self, model, input):  # noqa: A002
        class _Data:
            embedding = [0.1] * 3072
        class _Resp:
            data = [_Data()]
        return _Resp()


class _FakeChat:
    def create(self, model, messages, temperature):
        class _Choice:
            class message:
                content = "Test answer."
        class _Resp:
            choices = [_Choice()]
        return _Resp()


class _FakeOpenAI:
    embeddings = _FakeEmbedding()
    chat = type("Chat", (), {"completions": _FakeChat()})()


from local_agent import LocalInvoiceAgent
import chromadb


def _make_agent():
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("invoices-test")
    return LocalInvoiceAgent(
        store=local_store,
        chroma_collection=collection,
        openai_client=_FakeOpenAI(),
        gpt_deployment="gpt-4o",
        embedding_deployment="text-embedding-3-large",
    )


def test_index_and_stats():
    agent = _make_agent()
    agent.index_invoice(SAMPLE_RECORD)
    stats = agent.get_stats()
    assert stats["total_invoices"] == 1
    assert "EUR" in stats["currencies"]


def test_ask_returns_answer():
    agent = _make_agent()
    agent.index_invoice(SAMPLE_RECORD)
    response = agent.ask("What is the total?")
    assert response.answer == "Test answer."
    assert response.results is not None


def test_ask_error_is_graceful():
    agent = _make_agent()
    # No documents indexed — should still return an answer (empty context)
    response = agent.ask("What invoices exist?")
    assert isinstance(response.answer, str)
    assert response.error is None
