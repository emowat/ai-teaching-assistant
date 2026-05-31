"""
End-to-end test: RAG retrieval → Cohere Socratic TA response.
"""
import os
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from langchain_cohere import ChatCohere

from rag import close_client, generate_response, QueryInput, ASTFeatures, AssistMode

cohere_chat_model = ChatCohere(
    cohere_api_key=os.environ["COHERE_API_KEY"],
    model="command-xlarge-nightly",
)

# One call: retrieval (Layer 1+2) + Cohere generation (Layer 3)
try:
    answer = generate_response(
        query=QueryInput(
            student_message="Why does my program crash?",
            code_raw="int* p; *p = 5;",
            terminal_output="Segmentation fault (core dumped)",
            exit_code=139,
            week=3,
            mode=AssistMode.HOMEWORK_ASSIST,
            ast_features=ASTFeatures(has_pointer=True),
        ),
        llm=cohere_chat_model,
    )

    print(answer)
finally:
    close_client()
