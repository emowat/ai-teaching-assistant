import json
import sys
import os

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
                    
                    print(f"\n[{role}]:")
                    # Honoring newlines in the content
                    print(content)
                    print(f"{'-'*40}")
                    
            except json.JSONDecodeError:
                print(f"Error decoding JSON on line {i+1}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pretty print synthetic dataset.")
    parser.add_argument("--mode", type=str, choices=["train", "eval", "phase3"], default="train", help="train, eval mode or phase3 to select input file")
    args = parser.parse_args()
    
    if args.mode == "train":
        target_file = "synthetic_c_plus_plus_dataset.jsonl" 
    elif args.mode == "eval":
        target_file = "eval_c_plus_plus_dataset.jsonl"
    elif args.mode == "phase3":
        target_file = "phase3_paste_transcripts.jsonl"
    
    pretty_print_jsonl(target_file)
