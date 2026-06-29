import asyncio
from dotenv import load_dotenv
import os
import sys
import json
import argparse

parser = argparse.ArgumentParser(description="Evaluate a specific turn 1 from final_eval.jsonl")
parser.add_argument("--line", type=int, default=1, help="Line number to evaluate (1-indexed)")
parser.add_argument("--ollama", action="store_true", help="Use local Ollama instead of SageMaker")
parser.add_argument("--bedrock", action="store_true", help="Use AWS Bedrock (Claude) instead of SageMaker")
parser.add_argument("--dump", action="store_true", help="Dump the prompt to stdout instead of running inference")
args = parser.parse_args()

# Add rag_eng to path so we can import from it
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "rag_eng")))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

if args.ollama:
    os.environ["USE_SAGEMAKER"] = "false"
    os.environ["OLLAMA_MODEL"] = "codingrabbit-ta"
    print("Configured to use local Ollama instance (model: codingrabbit-ta).")
elif args.bedrock:
    os.environ["USE_SAGEMAKER"] = "false"
    print("Configured to use AWS Bedrock (Claude).")
else:
    # Ensure it uses SageMaker
    os.environ["USE_SAGEMAKER"] = "true"
    os.environ["SAGEMAKER_ENDPOINT"] = "codingrabbit-qwen-async-v22"
    os.environ["SAGEMAKER_INFERENCE_BACKEND"] = "vllm"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    print("Configured to use SageMaker endpoint: codingrabbit-qwen-async-v22.")

try:
    from inference import run_inference
    from config import get_settings
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

async def main():
    settings = get_settings()
    
    # Read the specified line from final_eval.jsonl
    eval_file = os.path.join(os.path.dirname(__file__), "synthetic-transcripts", "final_eval.jsonl")
    target_line = None
    with open(eval_file, "r") as f:
        for i, line in enumerate(f, 1):
            if i == args.line:
                target_line = line
                break
    
    if target_line is None:
        print(f"Error: Line {args.line} not found in {eval_file}")
        return
        
    data = json.loads(target_line)
    
    # Extract the system and user messages from turn 1
    messages = data["messages"]
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    
    if not system_msg or not user_msg:
        print("Could not find system or user message in the first turn.")
        return

    # Extract the baked system prompt to rescue the RAG context
    baked_system_content = system_msg["content"]
    
    # The baked system prompt usually has the RAG context after "19. CHAIN OF THOUGHT: ... </analysis>\nAfter the closing tag, provide your pedagogical response."
    # Let's just find the RAG context markers if they exist, or just use the live system prompt and hope RAG isn't strictly needed for this specific syntax test.
    # Create the exact prompt array for inference
    api_messages = [
        {"role": "system", "content": system_msg["content"]},
        {"role": "user", "content": user_msg["content"]}
    ]

    if args.dump:
        print("========== SYSTEM PROMPT ==========\n")
        print(system_msg["content"])
        print("\n========== USER PROMPT ==========\n")
        print(user_msg["content"])
        print("\n=================================")
        return

    target = "local Ollama" if args.ollama else ("AWS Bedrock" if args.bedrock else "SageMaker")
    print(f"Sending realistic IDE request (Turn 1, Line {args.line}) to CodingRabbit on {target}...\n")
    print("--- RESPONSE START ---\n")
    
    if args.ollama:
        from inference import _invoke_ollama
        response_stream = await _invoke_ollama(
            messages=api_messages,
            settings=settings,
            stream=True
        )
    elif args.bedrock:
        from inference import _invoke_bedrock
        response_stream = await _invoke_bedrock(
            messages=api_messages,
            settings=settings,
            stream=True
        )
    else:
        response_stream = await run_inference(
            messages=api_messages,
            model_name="qwen",
            settings=settings,
            stream=True
        )
    
    full_response = ""
    buffer = ""
    async for chunk in response_stream:
        # Handle parsed dictionaries (e.g. from openai/vllm non-sagemaker wrappers if they returned dicts)
        if isinstance(chunk, dict) and "message" in chunk:
            full_response += chunk["message"].get("content", "")
            continue
            
        # Handle byte streams (Ollama / SageMaker mock)
        text_chunk = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        buffer += text_chunk
        
        # Process complete lines
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                full_response += payload.get("message", {}).get("content", "")
            except json.JSONDecodeError:
                # If it's a completely unparseable line that isn't JSON, just append it
                full_response += line

    # Process any remaining text in the buffer
    if buffer.strip():
        try:
            payload = json.loads(buffer.strip())
            full_response += payload.get("message", {}).get("content", "")
        except json.JSONDecodeError:
            full_response += buffer.strip()

    print(full_response)
    print("\n\n--- RESPONSE END ---\n")

if __name__ == "__main__":
    asyncio.run(main())
