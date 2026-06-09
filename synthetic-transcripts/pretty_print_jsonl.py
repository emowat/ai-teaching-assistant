import json
import sys
import os

import re

def pretty_print_jsonl(filename):
    if not os.path.exists(filename):
        print(f"Error: File {filename} not found.")
        return

    with open(filename, 'r') as f:
        for i, line in enumerate(f):
            try:
                data = json.loads(line)
                print(f"\n{'='*80}")
                print(f" SESSION {i+1}")
                print(f"{'='*80}")
                
                if 'metadata' in data:
                    print("\n[METADATA]:")
                    meta = data['metadata']
                    print(f"  Problem ID: {meta.get('problem_id', 'N/A')} (Week {meta.get('week', '?')})")
                    print(f"  Trigger: {meta.get('trigger', 'N/A')}")
                    print(f"  Hidden Vulnerability: {meta.get('Hidden_Vulnerability', 'N/A')}")
                    print(f"  Hidden Trigger: {meta.get('Hidden_Trigger_Condition', 'N/A')}")
                    print(f"{'-'*40}")
                
                for msg in data.get('messages', []):
                    role = msg.get('role', 'unknown').upper()
                    content = msg.get('content', '')
                    
                    if role == 'SYSTEM':
                        # Extract everything from the CURRENT SESSION CONTEXT header downwards
                        context_match = re.search(r'^CURRENT SESSION CONTEXT:[\s\S]*', content, re.MULTILINE)
                        if context_match:
                            print(f"\n[SYSTEM CONTEXT BLOCKS]:")
                            print("\033[36m" + context_match.group(0) + "\033[0m")
                            print(f"{'-'*40}")
                        continue
                        
                    print(f"\n[{role}]:")
                    
                    if role == 'ASSISTANT' and '<analysis>' in content:
                        # Extract the analysis block
                        analysis_match = re.search(r'<analysis>([\s\S]*?)<\/analysis>', content)
                        if analysis_match:
                            analysis_text = analysis_match.group(1).strip()
                            print("\033[90m[HIDDEN CoT RATIONALE]\033[0m")
                            for a_line in analysis_text.split('\n'):
                                print(f"\033[90m  {a_line.strip()}\033[0m")
                            
                            # Print the actual response
                            actual_response = content.replace(analysis_match.group(0), '').strip()
                            print(f"\n{actual_response}")
                        else:
                            print(content)
                    else:
                        print(content)
                        
                    print(f"{'-'*40}")
                    
            except json.JSONDecodeError:
                print(f"Error decoding JSON on line {i+1}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pretty print synthetic dataset.")
    parser.add_argument("--mode", type=str, choices=["train", "eval", "augment_train", "augment_eval"], default="train", help="Which file to print")
    parser.add_argument("--file", type=str, help="Explicit file path to print, overrides mode.")
    args = parser.parse_args()
    
    if args.file:
        target_file = args.file
    else:
        if args.mode == "train":
            target_file = "synthetic_c_plus_plus_dataset.jsonl" 
        elif args.mode == "eval":
            target_file = "eval_c_plus_plus_dataset.jsonl"
        elif args.mode == "augment_train":
            target_file = "augmented_train_cot.jsonl"
        elif args.mode == "augment_eval":
            target_file = "augmented_eval_cot.jsonl"
    
    pretty_print_jsonl(target_file)
