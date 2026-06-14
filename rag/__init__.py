from .schemas import (
    ASTFeatures,
    AssistMode,
    ChunkPayload,
    CourseSource,
    DocCategory,
    QueryInput,
    RetrievedDoc,
    RetrievalResult,
    SourceDomain,
)
# Re-export the new prompt helper alongside the original public retrieval and
# generation entry points so the service layer can reuse the same RAG logic
# without reaching into internal modules directly.
from .loader import CppGuidelinesLoader, HarvardNotesLoader, HarvardTranscriptsLoader
from .pipeline import build_prompt, generate_response, generate_response_from_result, run_retrieval
from .retrievers import close_client, retrieve_guidelines, retrieve_harvard, retrieve_harvard_rules
