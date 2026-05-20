"""CLI wrapper: rebuild the AI Search index from Cosmos DB.

Usage:
    cd "<repo root>"
    source venv/bin/activate
    python scripts/rebuild_search_index.py

Requires az login with an identity that has:
  - Cosmos DB Built-in Data Reader on the Cosmos account
  - Search Index Data Contributor on the Search service
  - Cognitive Services OpenAI User on the Azure OpenAI resource
"""

import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sync import rebuild  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    result = rebuild(
        cosmos_endpoint=os.environ["COSMOS_ENDPOINT"],
        cosmos_database=os.environ["COSMOS_DATABASE"],
        cosmos_container=os.environ["COSMOS_CONTAINER"],
        search_endpoint=os.environ["SEARCH_ENDPOINT"],
        search_index=os.environ["SEARCH_INDEX"],
        openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        openai_api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        embed_deployment=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        progress_callback=lambda msg, _: log.info(msg),
    )
    log.info("Done — indexed: %d, errors: %d", result["indexed"], result["errors"])


if __name__ == "__main__":
    main()
