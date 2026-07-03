import json
import sys
from pathlib import Path
import argparse

# Ensure the root directory is in the PYTHONPATH so we can import output_guardrails
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
sys.path.append(str(root_dir))

from output_guardrails.combined import apply_all_guardrails

parser = argparse.ArgumentParser(description="Evaluate code leakage on a specific log file.")
parser.add_argument("log_path", type=str, help="Path to the .jsonl log file to evaluate")
args = parser.parse_args()

log_path = Path(args.log_path)
if not log_path.exists():
    print(f"Error: Log file {log_path} does not exist.")
    sys.exit(1)

eval_cases = []
with open(log_path, "r") as f:
    for line in f:
        if line.strip():
            eval_cases.append(json.loads(line))

print(f"Loaded {len(eval_cases)} evaluation cases from {log_path.name}")

blocked_count = 0
for i, data in enumerate(eval_cases):
    if "ta_generation_phase" not in data or not data["ta_generation_phase"]:
        continue
    
    # Check if this is a legitimate response (not an adversarial one that was stopped early)
    if "final_rendered_text" not in data["ta_generation_phase"]:
        continue
        
    student_input = data.get("student_phase", {}).get("raw_input", "")
    draft_answer = data["ta_generation_phase"].get("final_rendered_text", "")
    code_raw = data.get("ide_context", {}).get("raw_code_snippet", "")
    history = []
    
    if draft_answer.strip():
        # Apply output guardrails directly without spinning up a test client
        result = apply_all_guardrails(
            answer=draft_answer,
            user_query=student_input,
            student_code=code_raw,
            conversation_history=history
        )
        
        if result["blocked"] and result["violation_type"] == "code_leakage":
            blocked_count += 1
            print(f"\\n--- Code Leakage Blocked at Line {i + 1} ---")
            print(f"Evidence: {result['evidence']}")
            print(f"Draft Answer excerpt:\\n{draft_answer[:500]}")

print(f"\\nTotal code_leakage blocks: {blocked_count}")
