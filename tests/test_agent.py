"""Unit tests for the Phase 2 RAG agent (Azure clients mocked)."""

import pytest

from agent import build_agent


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
