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
    target_file = "synthetic_c_plus_plus_dataset.jsonl"
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    
    pretty_print_jsonl(target_file)
