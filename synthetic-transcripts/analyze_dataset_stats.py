import json
import sys

def analyze_dataset(filepath):
    print(f"Analyzing transcripts in {filepath}...\n")
    
    total_count = 0
    hw_assist_count = 0
    study_assist_count = 0
    oos_count = 0
    termination_count = 0
    style_flagged_count = 0
    
    with open(filepath, 'r') as f:
        for line in f:
            total_count += 1
            entry = json.loads(line)
            
            # Check Terminal Context for Mode
            metadata = entry.get("metadata", {})
            trigger = metadata.get("trigger", "")
            hidden_vuln = metadata.get("Hidden_Vulnerability", "")
            
            # Check for OOS
            if "Out-of-Scope" in trigger or "Out-of-Scope" in hidden_vuln or trigger == "Out-of-Scope":
                oos_count += 1
            else:
                messages = entry.get("messages", [])
                if len(messages) > 0:
                    system_prompt = messages[0].get("content", "")
                    if "Mode: Homework Assist" in system_prompt:
                        hw_assist_count += 1
                    elif "Mode: Study Assist" in system_prompt:
                        study_assist_count += 1
            
            # Check for Terminations
            messages = entry.get("messages", [])
            has_termination = False
            for msg in messages:
                if msg.get("role") == "assistant" and "[END_CHAT]" in msg.get("content", ""):
                    has_termination = True
                    break
            if has_termination:
                termination_count += 1
                
            # Check for Style Flagged
            has_style_flag = False
            for msg in messages:
                content_lower = msg.get("content", "").lower()
                if msg.get("role") == "assistant" and any(phrase in content_lower for phrase in ["style guide", "style issues", "guidelines", "format those"]):
                    has_style_flag = True
                    break
            
            if has_style_flag:
                style_flagged_count += 1

    print("=== Dataset Statistics ===")
    print(f"Total Transcripts:      {total_count}")
    print(f"Homework Assist:        {hw_assist_count} ({hw_assist_count/total_count:.1%})")
    print(f"Study Assist:           {study_assist_count} ({study_assist_count/total_count:.1%})")
    print(f"Out-of-Scope:           {oos_count} ({oos_count/total_count:.1%})")
    print("-" * 26)
    print(f"Terminations [END_CHAT]: {termination_count} ({termination_count/total_count:.1%})")
    print(f"Terminations (2 pivots): {termination_count - oos_count} ({(termination_count - oos_count)/total_count:.1%})")
    print(f"Style Flagged:          {style_flagged_count} ({style_flagged_count/total_count:.1%})")
    print("\n")

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze dataset statistics")
    parser.add_argument("--mode", choices=["train", "eval"], default="train", help="Dataset mode to analyze")
    parser.add_argument("filepath", nargs="?", help="Specific filepath (overrides mode)")
    
    args = parser.parse_args()
    
    if args.filepath:
        target_file = args.filepath
    else:
        target_file = "synthetic_c_plus_plus_dataset.jsonl" if args.mode == "train" else "eval_c_plus_plus_dataset.jsonl"
        
    analyze_dataset(target_file)
