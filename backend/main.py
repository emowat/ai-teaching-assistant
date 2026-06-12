from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
import uvicorn
import json
from prompts import get_system_prompt
from rag_client import expand_query, retrieve_rag_context

app = FastAPI(title="CodingRabbit Inference API")

UPSTREAM_OLLAMA_URL = "http://localhost:11434/api/chat"

@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """
    Thin Client Orchestrator:
    1. Intercepts payload
    2. Performs Query Expansion & RAG
    3. Assembles prompt
    4. Streams inference
    """
    try:
        payload = await request.json()
        messages = payload.get("messages", [])
        
        # In a real implementation, we would extract AST and Raw_Code from the VSCode payload.
        # For now, we just mock the context extraction from the last user message.
        last_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        
        if last_user_msg:
            content = last_user_msg["content"]
            
            # Determine mode
            mode = "Homework Assist"
            if "Mode: Study Assist" in content:
                mode = "Study Assist"

            # 1. Query Expansion
            expanded_query = await expand_query(content, "Mocked AST Context")
            
            # 2. RAG Retrieval
            rag_context = await retrieve_rag_context(expanded_query)
            
            # 3. Dynamic Prompt Assembly
            # If the VSCode extension sent an old system prompt, we strip it out.
            if messages and messages[0].get("role") == "system":
                messages.pop(0)
                
            # Inject our fresh centralized system prompt with the RAG context
            system_prompt_base = get_system_prompt(mode)
            full_system_prompt = f"{system_prompt_base}\n{rag_context}"
            messages.insert(0, {"role": "system", "content": full_system_prompt})
            
            payload["messages"] = messages
            print("--- FINAL PAYLOAD SENT TO OLLAMA ---")
            print(json.dumps(payload, indent=2))
            print("------------------------------------")
            
            is_streaming = payload.get("stream", True)
            USE_SAGEMAKER = os.environ.get("USE_SAGEMAKER", "false").lower() == "true"

            if USE_SAGEMAKER:
                import boto3
                import uuid
                import asyncio
                
                # SageMaker Async settings
                AWS_PROFILE = os.getenv("AWS_PROFILE", "codingrabbit-dev")
                AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
                S3_BUCKET = os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
                SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT", "codingrabbit-sagemaker-async-endpoint")
                
                # Format prompt for Llama 3 Instruct
                formatted_prompt = "<|begin_of_text|>"
                for msg in messages:
                    formatted_prompt += f"<|start_header_id|>{msg['role']}<|end_header_id|>\n\n{msg['content']}<|eot_id|>"
                formatted_prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
                
                # HuggingFace LMI / TGI standard payload
                sagemaker_payload = {
                    "inputs": formatted_prompt,
                    "parameters": {
                        "max_new_tokens": 2048,
                        "temperature": 0.7,
                        "top_p": 0.9
                    }
                }
                
                request_id = str(uuid.uuid4())
                input_s3_key = f"temp/sagemaker_inputs/{request_id}.json"
                
                session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
                s3_client = session.client("s3")
                sm_runtime = session.client("sagemaker-runtime")
                
                # 1. Upload payload to S3
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=input_s3_key,
                    Body=json.dumps(sagemaker_payload)
                )
                
                # 2. Invoke Async Endpoint
                response = sm_runtime.invoke_endpoint_async(
                    EndpointName=SAGEMAKER_ENDPOINT,
                    InputLocation=f"s3://{S3_BUCKET}/{input_s3_key}",
                    ContentType="application/json"
                )
                output_s3_uri = response["OutputLocation"]
                output_key = output_s3_uri.replace(f"s3://{S3_BUCKET}/", "")
                
                # 3. Poll for result
                print(f"Polling S3 for SageMaker Async output: {output_s3_uri}")
                full_llm_response = ""
                while True:
                    try:
                        result_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=output_key)
                        result_data = json.loads(result_obj["Body"].read().decode("utf-8"))
                        
                        # Extract the generated text (LMI container format)
                        if isinstance(result_data, list) and len(result_data) > 0 and "generated_text" in result_data[0]:
                            full_llm_response = result_data[0]["generated_text"]
                        elif "generated_text" in result_data:
                            full_llm_response = result_data["generated_text"]
                        else:
                            full_llm_response = str(result_data)
                        break
                    except s3_client.exceptions.NoSuchKey:
                        await asyncio.sleep(2.0)
                
                print("SageMaker response received!")
                
                # Write cleanly formatted log locally
                with open("orchestrator.log", "a") as log_file:
                    log_file.write(f"\n{'='*50}\n")
                    log_file.write("--- INCOMING STUDENT REQUEST (SAGEMAKER) ---\n")
                    log_file.write(last_user_msg["content"] + "\n\n")
                    log_file.write("--- GENERATED TA RESPONSE ---\n")
                    log_file.write(full_llm_response + "\n")
                    log_file.write(f"{'='*50}\n")

                # Mock an Ollama streaming response to the VSCode client
                async def mock_stream():
                    # Stream it back in chunks so the UI typing indicator works
                    chunk_size = 20
                    for i in range(0, len(full_llm_response), chunk_size):
                        chunk = full_llm_response[i:i+chunk_size]
                        yield json.dumps({"message": {"content": chunk}}) + "\n"
                        await asyncio.sleep(0.01)
                
                if is_streaming:
                    return StreamingResponse(mock_stream(), media_type="application/x-ndjson")
                else:
                    return {"message": {"content": full_llm_response}}

            else:
                # ========================================================
                # LOCAL OLLAMA PATH (Fallback for local testing)
                # ========================================================
                if not is_streaming:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(UPSTREAM_OLLAMA_URL, json=payload, timeout=300.0)
                        if response.status_code != 200:
                            print(f"OLLAMA HTTP {response.status_code} ERROR: {response.text}")
                            raise HTTPException(status_code=response.status_code, detail=response.text)
                        
                        data = response.json()
                        full_llm_response = data.get("message", {}).get("content", "")
                        
                        # Write cleanly formatted log locally
                        with open("orchestrator.log", "a") as log_file:
                            log_file.write(f"\n{'='*50}\n")
                            log_file.write("--- INCOMING STUDENT REQUEST ---\n")
                            log_file.write(last_user_msg["content"] + "\n\n")
                            log_file.write("--- GENERATED TA RESPONSE ---\n")
                            log_file.write(full_llm_response + "\n")
                            log_file.write(f"{'='*50}\n")
                            
                        return data
                else:
                    async def stream_generator():
                        full_llm_response = ""
                        async with httpx.AsyncClient() as client:
                            async with client.stream("POST", UPSTREAM_OLLAMA_URL, json=payload, timeout=300.0) as response:
                                if response.status_code != 200:
                                    yield json.dumps({"error": f"Upstream returned {response.status_code}"})
                                    return
                                
                                async for chunk in response.aiter_bytes():
                                    try:
                                        data = json.loads(chunk.decode("utf-8"))
                                        if "message" in data and "content" in data["message"]:
                                            full_llm_response += data["message"]["content"]
                                    except:
                                        pass
                                    yield chunk
                        
                        with open("orchestrator.log", "a") as log_file:
                            log_file.write(f"\n{'='*50}\n")
                            log_file.write("--- INCOMING STUDENT REQUEST ---\n")
                            log_file.write(last_user_msg["content"] + "\n\n")
                            log_file.write("--- GENERATED TA RESPONSE ---\n")
                            log_file.write(full_llm_response + "\n")
                            log_file.write(f"{'='*50}\n")

                    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

    except Exception as e:
        print(f"ERROR IN ORCHESTRATOR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
