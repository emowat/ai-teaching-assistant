import json
import re
import ast

def parse_save_txt():
    with open("synthetic_c_plus_plus_dataset.txt", "r") as f:
        content = f.read()

    sessions = re.split(r'={80}\n SESSION \d+\n={80}\n', content)
    
    parsed_entries = []
    
    for session in sessions:
        if not session.strip():
            continue
            
        messages = []
        metadata = {}
        
        # Parse METADATA block
        meta_match = re.search(r'\[METADATA\]:\n(.*?)\n-{40}', session, re.DOTALL)
        if meta_match:
            meta_text = meta_match.group(1)
            for line in meta_text.strip().split('\n'):
                line = line.strip()
                if line.startswith("Problem ID:"):
                    prob_part = line.split("Problem ID:")[1].strip()
                    metadata["problem_id"] = prob_part.split(" (")[0]
                    week_match = re.search(r'Week (\d+)', prob_part)
                    if week_match:
                        metadata["week"] = int(week_match.group(1))
                elif line.startswith("Trigger:"):
                    metadata["trigger"] = line.split("Trigger:")[1].strip()
                elif line.startswith("Hidden Vulnerability:"):
                    val = line.split("Hidden Vulnerability:")[1].strip()
                    if val != "N/A":
                        metadata["Hidden_Vulnerability"] = val
                elif line.startswith("Hidden Trigger:"):
                    val = line.split("Hidden Trigger:")[1].strip()
                    if val != "N/A":
                        metadata["Hidden_Trigger_Condition"] = val

        # Parse SYSTEM prompt
        sys_match = re.search(r'\[SYSTEM\]:\n(.*?)\n-{40}', session, re.DOTALL)
        if sys_match:
            sys_text = sys_match.group(1).strip()
            messages.append({"role": "system", "content": sys_text})
            
            # Extract raw code and ast_metadata from sys_text so patch_dataset can use it
            code_match = re.search(r'Raw_Code:\n(.*?)(\n\n|$)', sys_text, re.DOTALL)
            if code_match:
                code_text = code_match.group(1).strip()
                # Remove line numbers like "1: "
                clean_lines = []
                for cl in code_text.splitlines():
                    if ": " in cl:
                        clean_lines.append(cl.split(": ", 1)[-1])
                    else:
                        clean_lines.append(cl)
                metadata["code"] = "\n".join(clean_lines)
                
            ast_match = re.search(r'AST_Metadata:\n(.*?)(\n\n|$)', sys_text, re.DOTALL)
            if ast_match:
                ast_text = ast_match.group(1).strip()
                if ast_text.startswith("{"):
                    try:
                        metadata["ast_metadata"] = json.loads(ast_text)
                    except json.JSONDecodeError:
                        pass
                else:
                    ast_lines = ast_text.split('\n')
                    ast_metadata = {}
                    for al in ast_lines:
                        if al.startswith("- Focus_Scope:"):
                            parts = al.split('Focus_Scope: "')
                            if len(parts) > 1:
                                ast_metadata["Focus_Scope"] = parts[1].strip('"')
                        elif al.startswith("- Target_Variables:"):
                            arr_str = al.split('Target_Variables: ')[1].strip()
                            try:
                                ast_metadata["Target_Variables"] = json.loads(arr_str)
                            except json.JSONDecodeError:
                                pass
                        elif al.startswith("- Features:"):
                            feat_str = al.split('Features: ')[1].strip()
                            try:
                                ast_metadata["Features"] = json.loads(feat_str)
                            except json.JSONDecodeError:
                                pass
                    metadata["ast_metadata"] = ast_metadata
                
            # Extract Exit_Code and Output
            exit_code_match = re.search(r'Exit_Code: (\d+)', sys_text)
            if exit_code_match:
                metadata["expected_exit_code"] = int(exit_code_match.group(1))
            
            output_match = re.search(r'Output: "(.*?)"', sys_text)
            if output_match:
                metadata["expected_terminal_output"] = output_match.group(1)

        # Parse conversation turns
        conv_blocks = re.split(r'-{40}\n', session)
        for block in conv_blocks:
            block = block.strip()
            if block.startswith("[USER]:"):
                messages.append({"role": "user", "content": block.replace("[USER]:", "").strip()})
            elif block.startswith("[ASSISTANT]:"):
                messages.append({"role": "assistant", "content": block.replace("[ASSISTANT]:", "").strip()})
        
        if messages:
            parsed_entries.append({"messages": messages, "metadata": metadata})

    with open("synthetic_c_plus_plus_dataset.jsonl", "w") as f:
        for entry in parsed_entries:
            f.write(json.dumps(entry) + "\n")
            
    print(f"Successfully recovered {len(parsed_entries)} entries into synthetic_c_plus_plus_dataset.jsonl")

if __name__ == "__main__":
    parse_save_txt()
