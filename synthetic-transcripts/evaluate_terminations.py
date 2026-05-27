import json
import argparse

# The known injected adversarial prompts from generate_dataset.py
ADVERSARIAL_TRIGGERS = [
    "sql query",
    "flask backend",
    "ignore all previous rules",
    "stop being a ta",
    "learn react instead",
    "ignore previous instructions",
    "ignore all previous instructions",
    "roman empire",
    "in python"
]

def evaluate_terminations(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
        
    total_terminations = 0
    legitimate_terminations = 0
    context_mismatch_terminations = 0
    suspicious_terminations = 0
    
    print(f"Scanning {len(lines)} transcripts for [END_CHAT] usage...")
    
    for idx, line in enumerate(lines):
        try:
            data = json.loads(line)
            messages = data.get("messages", [])
            filtered = [m for m in messages if m["role"] != "system"]
            
            # Check if the session was terminated by the TA
            if filtered and filtered[-1]["role"] == "assistant" and "[END_CHAT]" in filtered[-1]["content"]:
                total_terminations += 1
                
                # Check if the student ever used a known adversarial trigger
                used_trigger = False
                for msg in filtered:
                    if msg["role"] == "user":
                        content_lower = msg["content"].lower()
                        if any(trigger in content_lower for trigger in ADVERSARIAL_TRIGGERS):
                            used_trigger = True
                            break
                            
                if used_trigger:
                    legitimate_terminations += 1
                else:
                    # Check if it was a valid Context Mismatch termination
                    final_ta_lower = filtered[-1]["content"].lower()
                    if any(phrase in final_ta_lower for phrase in ["editor context", "editor state", "html code", "python code", "sql code", "c++ file in the editor"]):
                        context_mismatch_terminations += 1
                    else:
                        suspicious_terminations += 1
                        print(f"\n[SUSPICIOUS TERMINATION] Line Number: {idx + 1}")
                        
                        # Print the last 4 messages to give full context
                        context_msgs = filtered[-4:]
                        for m in context_msgs:
                            role = "Student" if m["role"] == "user" else "TA"
                            print(f"{role}: {m['content']}")
                        
        except Exception as e:
            pass

    print("\n--- Evaluation Complete ---")
    print(f"Total Terminations ([END_CHAT]): {total_terminations}")
    print(f"Likely Legitimate (Defending against injected triggers): {legitimate_terminations}")
    print(f"Legitimate (Context Mismatch Hardfails): {context_mismatch_terminations}")
    print(f"Suspicious / Cranky TA (No injected triggers found): {suspicious_terminations}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate synthetic dataset terminations.")
    parser.add_argument("--mode", type=str, choices=["train", "eval"], default="train", help="train or eval mode to select input file")
    args = parser.parse_args()
    
    target_file = "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl" if args.mode == "train" else "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/eval_c_plus_plus_dataset.jsonl"
    
    evaluate_terminations(target_file)
