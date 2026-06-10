from .schemas import (
    ASTFeatures,
    AssistMode,
    ChunkPayload,
    DocCategory,
    QueryInput,
    RetrievedDoc,
    RetrievalResult,
    SourceDomain,
)
# Re-export the new prompt helper alongside the original public retrieval and
# generation entry points so the service layer can reuse the same RAG logic
# without reaching into internal modules directly.
from .loader import CppGuidelinesLoader
from .pipeline import build_prompt, generate_response, generate_response_from_result, run_retrieval
from .retrievers import close_client, retrieve_guidelines
