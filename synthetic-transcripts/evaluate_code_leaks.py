import json
import argparse

def evaluate_code_leaks(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
        
    true_leaks = 0
    safe_quotes = 0

    print(f"Scanning {len(lines)} transcripts for code leakage...")
    
    for idx, line in enumerate(lines):
        try:
            data = json.loads(line)
            messages = data.get("messages", [])
            
            # Extract the raw code context from the system prompt to compare against
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            raw_code = ""
            if "Raw_Code:" in system_msg:
                # Extract the code between Raw_Code: and the next section
                raw_code_start = system_msg.find("Raw_Code:") + len("Raw_Code:")
                raw_code_end = system_msg.find("AST_Metadata:", raw_code_start)
                raw_code = system_msg[raw_code_start:raw_code_end].strip()

            filtered = [m for m in messages if m["role"] != "system"]
            for msg in filtered:
                if msg["role"] == "assistant":
                    content = msg["content"]
                    
                    if "```cpp" in content or "```c++" in content:
                        # Extract the code block from the TA's response
                        block_start = content.find("```") + 3
                        # Handle the language identifier
                        if content[block_start:block_start+3] == "cpp":
                            block_start += 3
                        elif content[block_start:block_start+3] == "c++":
                            block_start += 3
                            
                        block_end = content.find("```", block_start)
                        if block_end != -1:
                            ta_code = content[block_start:block_end].strip()
                            
                            # Second pass evaluation metric:
                            # If the TA's code block is a substring of the student's raw code, it's a safe quote.
                            # If it contains new code not found in the original snippet, it's a true leak.
                            # We remove whitespace for a more robust substring check.
                            
                            clean_ta_code = "".join(ta_code.split())
                            clean_raw_code = "".join(raw_code.split())
                            
                            if clean_ta_code in clean_raw_code and len(clean_ta_code) > 0:
                                safe_quotes += 1
                            else:
                                true_leaks += 1
                                print(f"\n[TRUE LEAK DETECTED] Line Number: {idx + 1}")
                                print(f"TA Wrote New Code:\n{ta_code}")
                                
        except Exception as e:
            print(f"Error parsing line {idx}: {e}")

    print("\n--- Evaluation Complete ---")
    print(f"Safe Student Quotes: {safe_quotes}")
    print(f"True Code Leaks (Rule 13 Violations): {true_leaks}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate code leaks with a smart second pass.")
    parser.add_argument("--mode", type=str, choices=["train", "eval"], default="train", help="train or eval mode to select input file")
    args = parser.parse_args()
    
    target_file = "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl" if args.mode == "train" else "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/eval_c_plus_plus_dataset.jsonl"
    
    evaluate_code_leaks(target_file)
