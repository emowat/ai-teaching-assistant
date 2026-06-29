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
    collection_mit13: str
    collection_mit14: str
    collection_cs50: str
    collection_guidelines: str
    embedding_model: str
    raw_data_path: str

    @property
    def uses_remote_qdrant(self) -> bool:
        return bool(self.qdrant_url)

    def collection_for(self, course: str) -> str:
        """Map course source to Qdrant collection name."""
        return {
            "mit13": self.collection_mit13,
            "mit14": self.collection_mit14,
            "cs50": self.collection_cs50,
        }.get(course, self.collection_mit13)


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
        collection_mit13=os.getenv("QDRANT_COLLECTION_MIT13", "mit13_course"),
        collection_mit14=os.getenv("QDRANT_COLLECTION_MIT14", "mit14_course"),
        collection_cs50=os.getenv("QDRANT_COLLECTION_CS50", "harvard_cs50"),
        collection_guidelines=os.getenv("QDRANT_COLLECTION_GUIDELINES", "cpp_guidelines"),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "BAAI/bge-large-en-v1.5",
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
    timeout = int(os.getenv("QDRANT_TIMEOUT", "120"))
    if runtime.qdrant_url:
        # Hosted mode: use gRPC for reliable long-lived connections.
        # gRPC handles large payloads and keepalive natively (port 6334).
        return QdrantClient(
            url=runtime.qdrant_url,
            api_key=runtime.qdrant_api_key,
            timeout=timeout,
            prefer_grpc=True,
            grpc_port=6334,
            grpc_options={
                "grpc.keepalive_time_ms": 30_000,       # ping every 30s
                "grpc.keepalive_timeout_ms": 10_000,    # wait 10s for pong
                "grpc.keepalive_permit_without_calls": True,
                "grpc.http2.max_ping_strikes": 2,       # max failed pings before close
            },
        )
    # Local mode: preserve the original on-disk Qdrant workflow.
    return QdrantClient(path=runtime.qdrant_path)
