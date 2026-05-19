"""Unit tests for the Phase 2 RAG agent (Azure clients mocked)."""

import pytest
from unittest.mock import MagicMock

from agent import build_agent, InvoiceAgent, SELECT_FIELDS


@pytest.fixture
def mock_clients():
    """A (search_client, openai_client) pair of MagicMocks with sane defaults."""
    search = MagicMock()
    openai = MagicMock()
    openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])]
    )
    openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Test answer."))]
    )
    return search, openai


def test_retrieve_builds_hybrid_query(mock_clients):
    search, openai = mock_clients
    search.search.return_value = [{"id": "1", "supplier_name": "Acme"}]
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    docs = agent.retrieve("total spend?")

    assert docs == [{"id": "1", "supplier_name": "Acme"}]
    openai.embeddings.create.assert_called_once_with(
        model="emb-deploy", input="total spend?"
    )
    kwargs = search.search.call_args.kwargs
    assert kwargs["search_text"] == "total spend?"
    assert kwargs["top"] == 50
    assert kwargs["select"] == SELECT_FIELDS
    vector_query = kwargs["vector_queries"][0]
    assert vector_query.fields == "content_vector"
    assert vector_query.vector == [0.1, 0.2, 0.3]


def test_build_agent_missing_env_raises(monkeypatch):
    for var in (
        "SEARCH_ENDPOINT",
        "SEARCH_INDEX",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_GPT_DEPLOYMENT",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(EnvironmentError):
        build_agent()


def test_ask_returns_answer_and_records(mock_clients):
    search, openai = mock_clients
    search.search.return_value = [{"id": "1", "total_amount": 6875.0}]
    openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="The total is 6875.00 EUR."))]
    )
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    response = agent.ask("What is the total?")

    assert response.answer == "The total is 6875.00 EUR."
    assert response.results == [{"id": "1", "total_amount": 6875.0}]
    assert response.error is None
    # The question and answer are recorded for follow-up context.
    assert agent._history == [
        {"role": "user", "content": "What is the total?"},
        {"role": "assistant", "content": "The total is 6875.00 EUR."},
    ]


def test_ask_passes_prior_history_into_followup_prompt(mock_clients):
    search, openai = mock_clients
    search.search.return_value = [{"id": "1"}]
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    agent.ask("first question")
    agent.ask("follow-up question")

    messages = openai.chat.completions.create.call_args.kwargs["messages"]
    # System prompt, then the prior turn, then the current question.
    assert messages[0]["role"] == "system"
    assert {"role": "user", "content": "first question"} in messages
    assert {"role": "assistant", "content": "Test answer."} in messages
    assert messages[-1]["role"] == "user"
    assert "follow-up question" in messages[-1]["content"]


def test_ask_handles_empty_index(mock_clients):
    search, openai = mock_clients
    search.search.return_value = []
    openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="No invoices are indexed yet."))]
    )
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    response = agent.ask("How many invoices?")

    assert response.results == []
    assert response.error is None
    assert "no invoices" in response.answer.lower()


def test_ask_handles_retrieval_failure(mock_clients):
    search, openai = mock_clients
    search.search.side_effect = RuntimeError("search unreachable")
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    response = agent.ask("What is the total?")

    assert response.error == "search unreachable"
    assert response.results is None
    assert "couldn't reach" in response.answer.lower()


def test_ask_handles_answer_generation_failure(mock_clients):
    search, openai = mock_clients
    search.search.return_value = [{"id": "1"}]
    openai.chat.completions.create.side_effect = RuntimeError("model error")
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    response = agent.ask("What is the total?")

    assert response.error == "model error"
    assert response.results == [{"id": "1"}]
    assert "couldn't generate" in response.answer.lower()


def test_get_stats_counts_and_collects_currencies(mock_clients):
    search, openai = mock_clients
    paged = MagicMock()
    paged.get_count.return_value = 4
    # currency is filterable but not facetable in the index schema, so stats
    # are computed by scanning retrieved docs rather than via a facet query.
    paged.__iter__.return_value = iter([
        {"currency": "EUR"},
        {"currency": "USD"},
        {"currency": "EUR"},
        {"currency": None},
    ])
    search.search.return_value = paged
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    stats = agent.get_stats()

    assert stats == {"total_invoices": 4, "currencies": ["EUR", "USD"]}


def test_get_stats_returns_empty_on_failure(mock_clients):
    search, openai = mock_clients
    search.search.side_effect = RuntimeError("unreachable")
    agent = InvoiceAgent(search, openai, "gpt-4o", "emb-deploy")

    assert agent.get_stats() == {}
