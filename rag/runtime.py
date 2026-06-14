"""
Runtime configuration helpers for the RAG package.

This module is the small compatibility layer that lets the existing retrieval
code run against either local Qdrant or hosted Qdrant Cloud without changing
the public `rag.*` APIs. It also centralizes embedding and raw-data paths so
the new `rag_eng` service can read configuration from the environment in one
place instead of scattering it across retrieval and indexing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class RagRuntimeConfig:
    """Configuration for Qdrant, embeddings, and local source paths."""

    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_path: str
    collection_name: str
    guidelines_collection_name: str
    harvard_collection_name: str
    embedding_model: str
    raw_data_path: str

    @property
    def uses_remote_qdrant(self) -> bool:
        # The presence of a Qdrant URL is the switch that tells the repository
        # to talk to the hosted service instead of the legacy local directory.
        return bool(self.qdrant_url)


def get_runtime_config() -> RagRuntimeConfig:
    """Load runtime configuration from environment variables.

    The defaults preserve the original local development behavior, while the
    environment variables let `rag_eng` point the same retrieval code at Qdrant
    Cloud and a different embedding model if needed.
    """
    repo_root = Path(__file__).resolve().parent.parent
    default_qdrant_path = repo_root / "qdrant_local_data"
    default_raw_data_path = repo_root / "raw_data"

    return RagRuntimeConfig(
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        qdrant_path=os.getenv("QDRANT_PATH", str(default_qdrant_path)),
        collection_name=os.getenv("QDRANT_COLLECTION_NAME", "course_knowledge"),
        guidelines_collection_name=os.getenv(
            "QDRANT_GUIDELINES_COLLECTION_NAME", "cpp_guidelines",
        ),
        harvard_collection_name=os.getenv(
            "QDRANT_HARVARD_COLLECTION_NAME", "harvard_cs50",
        ),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        ),
        raw_data_path=os.getenv("RAW_DATA_PATH", str(default_raw_data_path)),
    )


def create_qdrant_client(config: RagRuntimeConfig | None = None):
    """Create a Qdrant client for local or hosted deployments.

    This helper hides the transport choice from callers so the rest of the RAG
    stack can continue to request a client without knowing whether it is
    connected to local disk-backed Qdrant or a remote cloud instance.
    """
    from qdrant_client import QdrantClient

    runtime = config or get_runtime_config()
    if runtime.qdrant_url:
        # Hosted mode: authenticate directly against the remote cluster.
        return QdrantClient(url=runtime.qdrant_url, api_key=runtime.qdrant_api_key)
    # Local mode: preserve the original on-disk Qdrant workflow.
    return QdrantClient(path=runtime.qdrant_path)
