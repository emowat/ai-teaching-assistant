"""LLM inference routing: SageMaker Async (production) or Ollama (local dev)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

import httpx

from rag_eng.config import Settings, get_inference_config
from rag_eng.prompt_budget import effective_max_tokens


# ---------------------------------------------------------------------------
# Chat template helpers (used only for the legacy huggingface backend)
# ---------------------------------------------------------------------------

def _format_messages(messages: list[dict], model_family: str) -> str:
    """Convert messages list to model-specific prompt format."""
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
    import sys
    from pathlib import Path

    import boto3

    deploy_dir = Path(__file__).resolve().parent.parent / "deploy"
    if str(deploy_dir) not in sys.path:
        sys.path.insert(0, str(deploy_dir))
    from sagemaker_io import build_async_payload, parse_async_response

    ic = get_inference_config().sagemaker
    backend = settings.sagemaker_inference_backend
    formatted_prompt = None
    if backend == "huggingface":
        formatted_prompt = _format_messages(messages, settings.model_family)

    max_tokens = effective_max_tokens(messages, ic)
    payload = build_async_payload(
        backend,
        messages,
        max_tokens=max_tokens,
        temperature=ic.generation.temperature,
        top_p=ic.generation.top_p,
        formatted_prompt=formatted_prompt,
    )

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
    failure_uri = response.get("FailureLocation")
    failure_key = (
        failure_uri.replace(f"s3://{bucket}/", "") if failure_uri else None
    )

    poll_interval = ic.poll_interval_seconds
    max_attempts = max(1, settings.sagemaker_poll_timeout_seconds // int(poll_interval))
    for _ in range(max_attempts):
        if failure_key:
            try:
                obj = s3.get_object(Bucket=bucket, Key=failure_key)
                failure_body = obj["Body"].read().decode()
                raise RuntimeError(
                    f"SageMaker async inference failed: {failure_body}"
                )
            except s3.exceptions.NoSuchKey:
                pass

        try:
            obj = s3.get_object(Bucket=bucket, Key=output_key)
            result = json.loads(obj["Body"].read().decode())
            return parse_async_response(backend, result)
        except s3.exceptions.NoSuchKey:
            await asyncio.sleep(poll_interval)

    raise TimeoutError(
        f"SageMaker async result not available after {int(max_attempts * poll_interval)}s. "
        "Endpoint may be cold-starting; retry in a few minutes."
    )


async def _stream_sagemaker(
    messages: list[dict],
    settings: Settings,
) -> AsyncIterator[bytes]:
    """Simulate streaming by chunking the SageMaker response."""
    ic = get_inference_config().sagemaker
    text = await _invoke_sagemaker(messages, settings)
    chunk_size = ic.streaming_chunk_size
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield (json.dumps({"message": {"content": chunk}}) + "\n").encode()
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Ollama local path
# ---------------------------------------------------------------------------

def _normalize_ollama_response(data: dict) -> dict:
    """Ensure message.content is populated for thinking-capable models."""
    message = data.get("message")
    if not isinstance(message, dict):
        return data
    content = message.get("content", "")
    if not content and message.get("thinking"):
        data = dict(data)
        data["message"] = {**message, "content": message["thinking"]}
    return data


async def _invoke_ollama(
    messages: list[dict],
    settings: Settings,
    stream: bool = False,
) -> dict | AsyncIterator[bytes]:
    """Forward messages to the local/Docker Ollama API.

    Model name comes from inference_config.yaml (ollama.model) which can be
    overridden with the OLLAMA_MODEL env var.  The name sent by the extension
    ("codingrabbit") is ignored — it does not match the Ollama model tag.
    """
    ic = get_inference_config().ollama
    url = ic.url  # OLLAMA_URL env var already applied in loader
    payload = {
        "model": ic.model,
        "messages": messages,
        "stream": stream,
        "think": ic.think,
        "options": {
            "temperature": ic.options.temperature,
            "top_p": ic.options.top_p,
            "num_ctx": ic.options.num_ctx,
            "num_predict": ic.options.num_predict,
        },
    }

    if not stream:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=ic.timeout_seconds)
            resp.raise_for_status()
            return _normalize_ollama_response(resp.json())

    async def _gen() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, json=payload, timeout=ic.timeout_seconds
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
    """Route to SageMaker or Ollama based on USE_SAGEMAKER setting.

    Returns:
        - dict with ``{"message": {"content": str}}`` when stream=False
        - AsyncIterator[bytes] of NDJSON chunks when stream=True
    """
    if settings.use_sagemaker:
        if stream:
            return _stream_sagemaker(messages, settings)
        text = await _invoke_sagemaker(messages, settings)
        return {"message": {"content": text}}

    return await _invoke_ollama(messages, settings, stream=stream)
