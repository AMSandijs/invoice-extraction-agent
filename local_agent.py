"""Local ChromaDB vector store + LocalInvoiceAgent — replaces Azure AI Search."""

import hashlib
import json
import os
import sys

import chromadb
from openai import AzureOpenAI

import local_store as _default_store

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "function_app"))
from search_indexer import build_content_summary  # noqa: E402

from agent import AgentResponse, ANSWER_SYSTEM_PROMPT, HISTORY_LIMIT, TOP_K

_CHROMA_PATH = os.environ.get("LOCAL_CHROMA_PATH") or os.path.join(
    os.path.dirname(__file__), "data", "chroma"
)


class LocalInvoiceAgent:
    """RAG agent backed by ChromaDB + SQLite instead of Azure AI Search + Cosmos."""

    def __init__(self, store, chroma_collection, openai_client, gpt_deployment, embedding_deployment):
        self._store = store
        self._col = chroma_collection
        self.openai_client = openai_client
        self.gpt_deployment = gpt_deployment
        self.embedding_deployment = embedding_deployment
        self._history: list[dict] = []

    def _embed(self, text: str) -> list[float]:
        response = self.openai_client.embeddings.create(
            model=self.embedding_deployment, input=text
        )
        return response.data[0].embedding

    def index_invoice(self, record: dict) -> None:
        """Embed a record and add it to ChromaDB + SQLite."""
        content = build_content_summary(record)
        vector = self._embed(content)
        doc_id = record.get("id") or hashlib.sha256(
            record.get("blob_name", "").encode()
        ).hexdigest()[:32]

        full_record = {**record, "id": doc_id, "content": content}
        self._store.upsert_invoice(full_record)

        self._col.upsert(
            ids=[doc_id],
            embeddings=[vector],
            documents=[content],
            metadatas=[{
                k: (str(v) if v is not None else "")
                for k, v in full_record.items()
                if k not in ("content",) and not isinstance(v, (list, dict))
            }],
        )

    def retrieve(self, question: str) -> list[dict]:
        """Embed the question and return the top-K closest invoice records."""
        vector = self._embed(question)
        n = min(TOP_K, self._col.count())
        if n == 0:
            return []
        results = self._col.query(
            query_embeddings=[vector],
            n_results=n,
            include=["metadatas", "documents"],
        )
        docs = []
        for meta, doc in zip(results["metadatas"][0], results["documents"][0]):
            row = dict(meta)
            row["content"] = doc
            for field in ("total_amount", "subtotal", "tax_amount"):
                if row.get(field) not in (None, "", "None"):
                    try:
                        row[field] = float(row[field])
                    except ValueError:
                        row[field] = None
            docs.append(row)
        return docs

    def _generate_answer(self, question: str, docs: list[dict]) -> str:
        records_text = json.dumps(docs, indent=2, default=str) if docs else "[]"
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            *self._history[-HISTORY_LIMIT:],
            {
                "role": "user",
                "content": f"Question: {question}\n\nInvoice records:\n{records_text}",
            },
        ]
        response = self.openai_client.chat.completions.create(
            model=self.gpt_deployment, messages=messages, temperature=0.3
        )
        return response.choices[0].message.content.strip()

    def ask(self, question: str) -> AgentResponse:
        try:
            docs = self.retrieve(question)
        except Exception as e:
            return AgentResponse(
                answer="I couldn't reach the local invoice index. Please try again.",
                error=str(e),
            )
        try:
            answer = self._generate_answer(question, docs)
        except Exception as e:
            return AgentResponse(
                answer="I retrieved the invoices but couldn't generate an answer.",
                results=docs,
                error=str(e),
            )
        self._history.append({"role": "user", "content": question})
        self._history.append({"role": "assistant", "content": answer})
        return AgentResponse(answer=answer, results=docs)

    def get_stats(self) -> dict:
        try:
            return {
                "total_invoices": self._store.get_invoice_count(),
                "currencies": self._store.get_currencies(),
            }
        except Exception:
            return {}


def build_local_agent() -> LocalInvoiceAgent:
    """Construct a LocalInvoiceAgent from environment config."""
    from agent import _require_env
    openai_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    api_key = _require_env("AZURE_OPENAI_API_KEY")
    gpt_deployment = _require_env("AZURE_OPENAI_GPT_DEPLOYMENT")
    embedding_deployment = _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        api_key=api_key,
        api_version=api_version,
    )

    if _CHROMA_PATH == ":memory:":
        chroma_client = chromadb.EphemeralClient()
    else:
        os.makedirs(_CHROMA_PATH, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=_CHROMA_PATH)

    collection = chroma_client.get_or_create_collection(
        name="invoices",
        metadata={"hnsw:space": "cosine"},
    )

    return LocalInvoiceAgent(
        store=_default_store,
        chroma_collection=collection,
        openai_client=openai_client,
        gpt_deployment=gpt_deployment,
        embedding_deployment=embedding_deployment,
    )
