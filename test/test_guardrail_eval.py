import json
import os
from pathlib import Path
import pytest
import requests
from urllib.parse import urljoin
from fastapi.testclient import TestClient

from rag_eng.api import create_app

EVAL_LOG_PATH = Path("synthetic-transcripts/final_eval_log.jsonl")

class RemoteClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
    
    def post(self, url: str, json: dict = None):
        return self.session.post(urljoin(self.base_url, url), json=json)

@pytest.fixture(scope="module")
def client():
    staging_url = os.environ.get("STAGING_API_URL")
    if staging_url:
        return RemoteClient(staging_url)
    return TestClient(create_app())

def load_eval_cases():
    """Load evaluation cases from the JSONL log file."""
    if not EVAL_LOG_PATH.exists():
        return []
    
    cases = []
    with open(EVAL_LOG_PATH, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            data = json.loads(line)
            cases.append((i, data))
    return cases

EVAL_CASES = load_eval_cases()

# Filter for adversarial inputs (blocked by input guardrail in the ground-truth log)
ADVERSARIAL_CASES = [
    (i, data) for i, data in EVAL_CASES 
    if data.get("input_guardrail_phase", {}).get("blocked") is True
]

EVAL_MODE = os.environ.get("EVAL_MODE", "smoke")
if EVAL_MODE == "smoke":
    ADVERSARIAL_CASES = ADVERSARIAL_CASES[:5]

# Filter for legitimate TA outputs (passed output guardrails in the ground-truth log)
LEGITIMATE_OUTPUT_CASES = []
for i, data in EVAL_CASES:
    ta_phase = data.get("ta_generation_phase")
    if not ta_phase:
        continue
    history = ta_phase.get("generation_history", [])
    if not history:
        continue
    # If the first attempt passed without being blocked, we consider it a legitimate output to test against
    first_attempt_guardrail = history[0].get("output_guardrail", {})
    if first_attempt_guardrail.get("blocked") is False:
        raw_gen = history[0].get("raw_generation", "")
        cot_keys = history[0].get("cot_keys", {})
        
        # Reconstruct the original full draft answer (with CoT) for the test payload
        full_draft = ""
        if cot_keys:
            full_draft += "<analysis>\n"
            for k, v in cot_keys.items():
                full_draft += f"- {k}: {v}\n"
            full_draft += "</analysis>\n\n"
        full_draft += raw_gen
        
        if full_draft.strip():
            LEGITIMATE_OUTPUT_CASES.append((i, data, full_draft.strip()))
            
if EVAL_MODE == "smoke":
    LEGITIMATE_OUTPUT_CASES = LEGITIMATE_OUTPUT_CASES[:5]


@pytest.mark.skipif(not EVAL_CASES, reason="Evaluation log not found")
@pytest.mark.parametrize("line_idx, data", ADVERSARIAL_CASES, ids=[f"line_{i}" for i, _ in ADVERSARIAL_CASES])
def test_input_guardrail_catches_adversarial_prompts(client: TestClient, line_idx: int, data: dict):
    student_input = data["student_phase"]["raw_input"]
    mode = data.get("ide_context", {}).get("mode", "Homework Assist")
    
    payload = {
        "student_message": student_input,
        "mode": mode,
        "course_id": data.get("course", {}).get("course_id", "cs50"),
        "week": 1,
    }
    
    response = client.post("/api/diagnostics/input-guardrail", json=payload)
    assert response.status_code == 200, response.text
    
    result = response.json()
    assert result["blocked"] is True, f"Failed to block adversarial input: {student_input}"


@pytest.mark.skipif(not EVAL_CASES, reason="Evaluation log not found")
@pytest.mark.parametrize("line_idx, data, draft_answer", LEGITIMATE_OUTPUT_CASES, ids=[f"line_{i}" for i, _, _ in LEGITIMATE_OUTPUT_CASES])
def test_output_guardrail_allows_legitimate_responses(client: TestClient, line_idx: int, data: dict, draft_answer: str):
    student_input = data["student_phase"]["raw_input"]
    mode = data.get("ide_context", {}).get("mode", "Homework Assist")
    
    # Reconstruct prior warnings for the guardrail if the student was already warned
    warnings = data.get("orchestrator_state", {}).get("adversarial_warnings", 0)
    history = []
    if warnings > 0:
        history.append({"role": "assistant", "content": "I cannot answer that. [ADVERSARIAL_WARNING]"})
    history.append({"role": "user", "content": student_input})

    payload = {
        "student_message": student_input,
        "mode": mode,
        "course_id": data.get("course", {}).get("course_id", "cs50"),
        "week": 1,
        "draft_answer": draft_answer,
        "code_raw": data.get("ide_context", {}).get("raw_code_snippet", ""),
        "conversation_history": history
    }
    
    response = client.post("/api/diagnostics/output-guardrail", json=payload)
    assert response.status_code == 200, response.text
    
    result = response.json()
    assert result["guardrail"]["blocked"] is False, f"Falsely blocked! Violation: {result['guardrail']['violation_type']}. Answer: {draft_answer}"
