import json
import argparse

def analyze_stats(filename):
    out_of_scope_count = 0
    study_assist_count = 0
    homework_assist_count = 0
    end_chat_count = 0
    
    with open(filename, 'r') as f:
        lines = f.readlines()
        
    print(f"Analyzing {len(lines)} transcripts in {filename}...\n")
    
    for idx, line in enumerate(lines):
        try:
            data = json.loads(line)
            meta = data.get("metadata", {})
            messages = data.get("messages", [])
            
            # Determine problem type
            trigger = meta.get("trigger", "")
            problem_id = meta.get("problem_id", "")
            
            if trigger == "Out-of-Scope" or problem_id.startswith("out_of_scope"):
                out_of_scope_count += 1
            elif trigger == "study_assist" or problem_id.startswith("study_mode"):
                study_assist_count += 1
            else:
                homework_assist_count += 1
                
            # Check for END_CHAT
            has_end_chat = False
            for msg in messages:
                if msg.get("role") == "assistant" and "[END_CHAT]" in msg.get("content", ""):
                    has_end_chat = True
                    break
                    
            if has_end_chat:
                end_chat_count += 1
                
        except Exception as e:
            print(f"Error parsing line {idx+1}: {e}")

    print("=== Dataset Statistics ===")
    print(f"Total Transcripts:      {len(lines)}")
    print(f"Homework Assist:        {homework_assist_count}")
    print(f"Study Assist:           {study_assist_count}")
    print(f"Out-of-Scope:           {out_of_scope_count}")
    print(f"--------------------------")
    print(f"Terminations [END_CHAT]: {end_chat_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze dataset statistics (out-of-scope, study assist, etc).")
    parser.add_argument("--mode", type=str, choices=["train", "eval"], default="train", help="train or eval mode to select input file")
    args = parser.parse_args()
    
    target_file = "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl" if args.mode == "train" else "/Users/mowat/Documents/Berkeley/repos/210/ai-teaching-assistant/synthetic-transcripts/eval_c_plus_plus_dataset.jsonl"
    
    analyze_stats(target_file)
