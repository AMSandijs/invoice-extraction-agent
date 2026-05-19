"""Invoice RAG agent — hybrid retrieval over Azure AI Search.

Replaces the Phase 1 Text-to-SQL agent. Embeds the question, runs a hybrid
keyword+vector search against the invoices-idx index, and answers with GPT-4o.
Auth is AAD via DefaultAzureCredential — no secrets on disk.
"""

import os
import json
from dataclasses import dataclass

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

load_dotenv()

# Documents retrieved per question. At demo scale this is >= the whole
# dataset, so GPT-4o can aggregate (totals, averages) over everything.
TOP_K = 50

# Recent conversation turns kept for follow-up context (3 user+assistant pairs).
HISTORY_LIMIT = 6

_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

# Fields pulled back from Search — everything except the embedding vector.
SELECT_FIELDS = [
    "id", "supplier_name", "buyer_name", "invoice_number", "po_number",
    "currency", "invoice_date", "due_date", "total_amount", "subtotal",
    "tax_amount", "blob_name", "content",
]

ANSWER_SYSTEM_PROMPT = """You are a helpful invoice assistant. You answer
questions using ONLY the invoice records provided to you.

Rules:
- Base every answer strictly on the provided invoice records.
- For totals, averages, counts, or "which is highest" questions, compute the
  answer from all provided records.
- Include actual numbers, supplier names, and invoice numbers in your answer.
- Format currency amounts with 2 decimal places.
- If no records are provided, say there are no invoices indexed yet.
- If the records do not contain the answer, say so — never invent data.
- For greetings or general chit-chat, respond naturally and briefly, and
  invite the user to ask about their invoice data.
- Keep answers to 1-3 sentences unless a list is needed.
"""


@dataclass
class AgentResponse:
    answer: str
    results: list | None = None
    error: str | None = None


def _require_env(name: str) -> str:
    """Return an environment variable's value, or raise if missing/empty."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Required environment variable {name} is not set.")
    return value


class InvoiceAgent:
    """Hybrid-RAG agent over the invoices-idx Search index.

    Clients are injected so the agent can be unit-tested without Azure.
    Use build_agent() to construct one from environment configuration.
    """

    def __init__(self, search_client, openai_client, gpt_deployment, embedding_deployment):
        self.search_client = search_client
        self.openai_client = openai_client
        self.gpt_deployment = gpt_deployment
        self.embedding_deployment = embedding_deployment
        self._history: list[dict] = []


def build_agent() -> InvoiceAgent:
    """Construct an InvoiceAgent from environment config, using AAD auth."""
    search_endpoint = _require_env("SEARCH_ENDPOINT")
    search_index = _require_env("SEARCH_INDEX")
    openai_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    gpt_deployment = _require_env("AZURE_OPENAI_GPT_DEPLOYMENT")
    embedding_deployment = _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    credential = DefaultAzureCredential()
    search_client = SearchClient(search_endpoint, search_index, credential)
    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        azure_ad_token_provider=get_bearer_token_provider(credential, _COGNITIVE_SCOPE),
        api_version=api_version,
    )
    return InvoiceAgent(search_client, openai_client, gpt_deployment, embedding_deployment)
