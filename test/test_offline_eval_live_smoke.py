from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import date

import pytest
from dotenv import load_dotenv

from rag_eng.chat_log_export import export_turn_snapshots_to_s3


load_dotenv()


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_PIPELINE_SMOKE", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="Live pipeline smoke is opt-in via RUN_LIVE_PIPELINE_SMOKE=1.",
)


def _run_curl_chat(base_url: str, payload: dict[str, object]) -> dict[str, object]:
    curl = shutil.which("curl")
    if not curl:
        pytest.skip("curl is not installed on this machine.")

    command = [
        curl,
        "-sS",
        "--fail",
        "--max-time",
        os.getenv("LIVE_PIPELINE_CURL_TIMEOUT_SECONDS", "180"),
        "-X",
        "POST",
        f"{base_url.rstrip('/')}/api/chat",
        "-H",
        "Content-Type: application/json",
        "-d",
        json.dumps(payload),
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _fetch_turn_snapshot(database_url: str, turn_id: str) -> tuple[dict[str, object], date]:
    psycopg = pytest.importorskip("psycopg")
    deadline = time.time() + float(
        os.getenv("LIVE_PIPELINE_DB_TIMEOUT_SECONDS", "30")
    )
    while True:
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT snapshot, created_at
                    FROM tutor_turn_snapshots
                    WHERE turn_id = %s
                    """,
                    (turn_id,),
                )
                row = cursor.fetchone()
                if row is not None:
                    snapshot = row[0]
                    if isinstance(snapshot, str):
                        snapshot = json.loads(snapshot)
                    return snapshot, row[1].date()
        if time.time() >= deadline:
            raise AssertionError(
                f"No turn snapshot found in Aurora for turn_id={turn_id}"
            )
        time.sleep(1)


def test_live_pipeline_chat_persists_snapshot_and_exports_to_s3() -> None:
    base_url = os.getenv("LIVE_CHAT_API_BASE_URL", "http://127.0.0.1:8001")
    database_url = (
        os.getenv("COURSE_REGISTRY_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not database_url:
        raise RuntimeError(
            "COURSE_REGISTRY_DATABASE_URL or DATABASE_URL must be set for the live pipeline smoke test."
        )
    s3_bucket = os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
    course_id = os.getenv("LIVE_PIPELINE_COURSE_ID", "mit14")
    export_connect_timeout_seconds = int(
        os.getenv("LIVE_PIPELINE_EXPORT_DB_CONNECT_TIMEOUT_SECONDS", "20")
    )

    request_id = f"live-smoke-{uuid.uuid4().hex}"
    session_id = f"live-smoke-{uuid.uuid4().hex}"
    turn_id = f"live-smoke-{uuid.uuid4().hex}"

    payload = {
        "model": "codingrabbit-ta",
        "course_id": course_id,
        "session_id": session_id,
        "request_id": request_id,
        "turn_id": turn_id,
        "result_count": 4,
        "rerank_strategy": "similarity",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Mode: Homework Assist\n"
                    "Week: 1\n"
                    "[Student_Question]\n"
                    "Can you explain how a for loop works in C++?"
                ),
            }
        ],
        "stream": False,
    }

    response = _run_curl_chat(base_url, payload)

    assert response["turn_id"] == turn_id
    assert response["session_id"] == session_id
    assert response["request_id"] == request_id
    assert response["message"]["content"]

    snapshot, snapshot_date = _fetch_turn_snapshot(database_url, turn_id)

    assert snapshot["trace"]["turn_id"] == turn_id
    assert snapshot["trace"]["session_id"] == session_id
    assert snapshot["trace"]["request_id"] == request_id
    assert snapshot["student_phase"]["input_guardrail"]["blocked"] is False
    assert snapshot["final_response"]["text"] == response["message"]["content"]
    assert snapshot["final_response"]["source"] in {"model", "output_guardrail"}

    exported = export_turn_snapshots_to_s3(
        database_url=database_url,
        bucket=s3_bucket,
        prefix="eval/chat_logs/turn_logs",
        start_date=snapshot_date,
        end_date=snapshot_date,
        course_id=course_id,
        profile=os.getenv("AWS_PROFILE"),
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        connect_timeout_seconds=export_connect_timeout_seconds,
    )

    assert exported
    assert exported[0]["s3_uri"].startswith(f"s3://{s3_bucket}/")

    boto3 = pytest.importorskip("boto3")
    s3_client = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE") or None,
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
    ).client("s3")
    key = exported[0]["key"]
    body = s3_client.get_object(Bucket=s3_bucket, Key=key)["Body"].read().decode("utf-8")
    assert turn_id in body
