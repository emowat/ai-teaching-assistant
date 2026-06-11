import json
import sys

def analyze_dataset(filepath):
    print(f"Analyzing transcripts in {filepath}...\n")
    
    total_count = 0
    hw_assist_count = 0
    study_assist_count = 0
    api_syntax_count = 0
    oos_count = 0
    migration_count = 0
    termination_count = 0
    style_flagged_count = 0
    paste_detected_count = 0
    debug_ideas_count = 0
    conceptual_questions_count = 0
    frustration_empathetic_count = 0
    frustration_adversarial_count = 0
    oos_termination_count = 0
    adversarial_termination_count = 0
    two_pivot_termination_count = 0
    
    vulnerability_distribution = {}
    
    with open(filepath, 'r') as f:
        for line in f:
            total_count += 1
            entry = json.loads(line)
            
            # Check Terminal Context for Mode
            metadata = entry.get("metadata", {})
            trigger = metadata.get("trigger", "")
            hidden_vuln = metadata.get("Hidden_Vulnerability", "")
            if hidden_vuln:
                vulnerability_distribution[hidden_vuln] = vulnerability_distribution.get(hidden_vuln, 0) + 1
            
            messages = entry.get("messages", [])
            system_prompt = messages[0].get("content", "") if len(messages) > 0 else ""
            
            # Check for OOS
            is_oos = False
            if "Out-of-Scope" in trigger or "Out-of-Scope" in hidden_vuln or trigger == "Out-of-Scope":
                oos_count += 1
                is_oos = True
            elif metadata.get("problem_id") == "creative_c_to_cpp":
                migration_count += 1
            else:
                if "Mode: Homework Assist" in system_prompt:
                    if trigger == "homework_api_query":
                        api_syntax_count += 1
                    else:
                        hw_assist_count += 1
                elif "Mode: Study Assist" in system_prompt:
                    study_assist_count += 1
            
            # Check for Terminations
            has_termination = False
            has_adversarial_warning = False
            for msg in messages:
                if msg.get("role") == "assistant":
                    if "[END_CHAT]" in msg.get("content", ""):
                        has_termination = True
                    if "[ADVERSARIAL_WARNING]" in msg.get("content", ""):
                        has_adversarial_warning = True
                        
            if has_termination:
                termination_count += 1
                if is_oos:
                    oos_termination_count += 1
                elif has_adversarial_warning:
                    adversarial_termination_count += 1
                else:
                    two_pivot_termination_count += 1
                
            # Parse CoT fields
            for msg in messages:
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    
                    if "<analysis>" in content:
                        # Extract the analysis block
                        analysis_block = content.split("</analysis>")[0]
                        
                        # Check Frustration Level
                        if "Frustration Level: 4" in analysis_block or "Frustration Level: 5" in analysis_block:
                            if "[END_CHAT]" in content or "[ADVERSARIAL_WARNING]" in content:
                                frustration_adversarial_count += 1
                            else:
                                frustration_empathetic_count += 1
                        
                        # Parse Paste_Detection_Check
                        if "- Paste_Detection_Check:" in analysis_block:
                            if "true" in analysis_block.split("- Paste_Detection_Check:")[1].split("\n")[0].lower() and "false" not in analysis_block.split("- Paste_Detection_Check:")[1].split("\n")[0].lower():
                                paste_detected_count += 1
                                
                        if "[STYLE_NUDGE]" in content:
                            style_flagged_count += 1
                                
                        # Parse Reward_Check
                        if "- Reward_Check:" in analysis_block:
                            reward_line = analysis_block.split("- Reward_Check:")[1].split("\n")[0].lower()
                            if "yes" in reward_line and "not " not in reward_line and "no " not in reward_line:
                                debug_ideas_count += 1
                                
                        # Parse Adversarial_Check
                        if "- Adversarial_Check:" in analysis_block:
                            adv_line = analysis_block.split("- Adversarial_Check:")[1].split("\n")[0].lower()
                            # It's an adversarial trigger if it issues a warning or ends chat
                            if "warning" in adv_line or "end_chat" in adv_line or "yes" in adv_line:
                                pass # We are already tracking terminations separately, but we could track warnings here
                                
                        # Parse Pivot_Check
                        if "- Pivot_Check:" in analysis_block:
                            pivot_line = analysis_block.split("- Pivot_Check:")[1].split("\n")[0].lower()
                            if "yes" in pivot_line and "not " not in pivot_line and "no " not in pivot_line:
                                conceptual_questions_count += 1
                            elif "[1](http" in content:
                                conceptual_questions_count += 1

    print("=== Dataset Statistics ===")
    print(f"Total Transcripts:      {total_count}")
    print(f"Homework Assist (Debug):{hw_assist_count} ({hw_assist_count/total_count:.1%})")
    print(f"Homework Assist (API):  {api_syntax_count} ({api_syntax_count/total_count:.1%})")
    print(f"Study Assist:           {study_assist_count} ({study_assist_count/total_count:.1%})")
    print(f"Out-of-Scope:           {oos_count} ({oos_count/total_count:.1%})")
    print(f"Migrations (C->C++):    {migration_count} ({migration_count/total_count:.1%})")
    print("-" * 26)
    print(f"Terminations [END_CHAT]: {termination_count} ({termination_count/total_count:.1%})")
    print(f"Terminations OOS:        {oos_termination_count} ({oos_termination_count/total_count:.1%})")
    print(f"Terminations Adversarial:{adversarial_termination_count} ({adversarial_termination_count/total_count:.1%})")
    print(f"Terminations 2-Pivot:    {two_pivot_termination_count} ({two_pivot_termination_count/total_count:.1%})")
    print(f"Paste Detected:         {paste_detected_count} ({paste_detected_count/total_count:.1%})")
    print(f"Empathetic Frustration: {frustration_empathetic_count} (L4/L5 + Human TA)")
    print(f"Adversarial Frustration:{frustration_adversarial_count} (L4/L5 + END/WARN)")
    print(f"Debug Ideas Unlocked:   {debug_ideas_count} (total tags)")
    print(f"Conceptual Questions:   {conceptual_questions_count} (via Pivot_Check)")
    print(f"Style Flagged:          {style_flagged_count} ({style_flagged_count/total_count:.1%})")
    print("-" * 26)
    print("Vulnerability Distribution:")
    for v, count in sorted(vulnerability_distribution.items(), key=lambda x: x[1], reverse=True):
        print(f" - {v[:50].ljust(50)} : {count}")
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
        target_file = "homework_debug_dataset.jsonl"
        
    analyze_dataset(target_file)
