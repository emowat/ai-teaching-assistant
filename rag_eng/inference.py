"""LLM inference routing: SageMaker Async (production) or Ollama (local dev)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

import httpx

from rag_eng.config import Settings


# ---------------------------------------------------------------------------
# Chat template helpers
# ---------------------------------------------------------------------------

def _format_messages(messages: list[dict], model_family: str) -> str:
    """Convert messages list to the model-specific prompt format."""
    if model_family == "llama3":
        prompt = "<|begin_of_text|>"
        for msg in messages:
            prompt += (
                f"<|start_header_id|>{msg['role']}<|end_header_id|>\n\n"
                f"{msg['content']}<|eot_id|>"
            )
        prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
        return prompt

    if model_family == "qwen":
        prompt = ""
        for msg in messages:
            prompt += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        return prompt

    # generic / chatml fallback
    prompt = ""
    for msg in messages:
        prompt += f"### {msg['role'].capitalize()}\n{msg['content']}\n"
    prompt += "### Assistant\n"
    return prompt


# ---------------------------------------------------------------------------
# SageMaker Async path
# ---------------------------------------------------------------------------

async def _invoke_sagemaker(
    messages: list[dict],
    settings: Settings,
) -> str:
    """Upload prompt to S3, invoke SageMaker Async endpoint, poll for result."""
    import boto3

    model_family = settings.model_family
    formatted_prompt = _format_messages(messages, model_family)

    payload = {
        "inputs": formatted_prompt,
        "parameters": {
            "max_new_tokens": 2048,
            "temperature": 0.7,
            "top_p": 0.9,
        },
    }

    request_id = str(uuid.uuid4())
    input_key = f"temp/sagemaker_inputs/{request_id}.json"
    bucket = settings.s3_data_bucket

    session = boto3.Session(
        profile_name=settings.aws_profile or None,
        region_name=settings.aws_region,
    )
    s3 = session.client("s3")
    sm_runtime = session.client("sagemaker-runtime")

    s3.put_object(Bucket=bucket, Key=input_key, Body=json.dumps(payload))

    response = sm_runtime.invoke_endpoint_async(
        EndpointName=settings.sagemaker_endpoint,
        InputLocation=f"s3://{bucket}/{input_key}",
        ContentType="application/json",
    )
    output_uri = response["OutputLocation"]
    output_key = output_uri.replace(f"s3://{bucket}/", "")

    # Poll S3 until result appears (2 s intervals, 60 s max)
    for _ in range(30):
        try:
            obj = s3.get_object(Bucket=bucket, Key=output_key)
            result = json.loads(obj["Body"].read().decode())
            if isinstance(result, list) and result and "generated_text" in result[0]:
                return result[0]["generated_text"]
            return result.get("generated_text", str(result))
        except s3.exceptions.NoSuchKey:
            await asyncio.sleep(2.0)

    raise TimeoutError("SageMaker async result not available after 60 s.")


async def _stream_sagemaker(
    messages: list[dict],
    settings: Settings,
    chunk_size: int = 20,
) -> AsyncIterator[bytes]:
    """Simulate streaming by chunking the SageMaker response."""
    text = await _invoke_sagemaker(messages, settings)
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield (json.dumps({"message": {"content": chunk}}) + "\n").encode()
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Ollama local path
# ---------------------------------------------------------------------------

async def _invoke_ollama(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
) -> dict | AsyncIterator[bytes]:
    """Forward the messages to the local Ollama API."""
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": 0.7, "top_p": 0.9, "num_ctx": 8192, "num_predict": 2048},
    }

    if not stream:
        async with httpx.AsyncClient() as client:
            resp = await client.post(settings.ollama_url, json=payload, timeout=300.0)
            resp.raise_for_status()
            return resp.json()

    async def _gen() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", settings.ollama_url, json=payload, timeout=300.0
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return _gen()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def run_inference(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
) -> dict | AsyncIterator[bytes]:
    """Route to SageMaker or Ollama based on settings.

    Returns:
        - dict with ``{"message": {"content": str}}`` when stream=False
        - AsyncIterator[bytes] of NDJSON chunks when stream=True
    """
    if settings.use_sagemaker:
        if stream:
            return _stream_sagemaker(messages, settings)
        text = await _invoke_sagemaker(messages, settings)
        return {"message": {"content": text}}

    return await _invoke_ollama(messages, model_name, settings, stream=stream)
