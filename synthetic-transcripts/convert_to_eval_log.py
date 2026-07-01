import json
import uuid
import re
import random
from datetime import datetime, timedelta

def extract_session_context(content, state):
    # Extract Raw Code
    code_match = re.search(r'Raw_Code:\n(.*?)(?=\nAST_Metadata:|\n\[|$)', content, re.DOTALL)
    if code_match:
        state["raw_code_snippet"] = code_match.group(1).strip()
        
    # Extract AST metadata robustly
    ast_match = re.search(r'AST_Metadata:\n(.*?)(?=\n\[|$)', content, re.DOTALL)
    if ast_match:
        if "ast_metadata" not in state or not isinstance(state["ast_metadata"], dict):
            state["ast_metadata"] = {}
            
        # Default Near_Cursor_STL to empty array to maintain schema consistency
        state["ast_metadata"]["Near_Cursor_STL"] = []
            
        for line in ast_match.group(1).split('\n'):
            if 'Features:' in line:
                m = re.search(r'(\{.*?\})', line)
                if m:
                    try:
                        feat_str = m.group(1).replace("'", '"').replace("False", "false").replace("True", "true")
                        state["ast_metadata"]["Features"] = json.loads(feat_str)
                    except Exception:
                        pass
            elif 'Target_Variables:' in line:
                m = re.search(r'(\{.*?\})', line)
                if m:
                    try:
                        state["ast_metadata"]["Target_Variables"] = json.loads(m.group(1))
                    except Exception:
                        pass
            elif 'Focus_Scope:' in line:
                m = re.search(r'Focus_Scope:\s*"(.*?)"', line)
                if m:
                    state["ast_metadata"]["Focus_Scope"] = m.group(1)
            elif 'Near_Cursor_STL:' in line:
                m = re.search(r'Near_Cursor_STL:\s*(\[.*?\])', line)
                if m:
                    try:
                        state["ast_metadata"]["Near_Cursor_STL"] = json.loads(m.group(1))
                    except Exception:
                        pass
                        
    # Extract Mode and Paste Detection
    mode_match = re.search(r'Mode:\s*(.*?)\n', content)
    if mode_match:
        state["mode"] = mode_match.group(1).strip()
        
    paste_match = re.search(r'Likely_Paste_Detected:\s*(true|false)', content, re.IGNORECASE)
    if paste_match:
        if paste_match.group(1).lower() == 'true':
            state["clipboard_event"] = {
                "external_paste_detected": True,
                "pasted_char_count": random.randint(100, 2000)
            }
        else:
            state["clipboard_event"] = None
            
    # Extract Terminal Context
    term_match = re.search(r'\[Terminal_Context\]\n(.*?)(?=\n\[|$)', content, re.DOTALL)
    if term_match:
        state["terminal_context"] = term_match.group(1).strip()
                        
    # Extract RAG Chunks
    rag_match = re.search(r'\[Vector_Database_Results\]\n(.*)', content, re.DOTALL)
    if rag_match:
        rag_text = rag_match.group(1).strip()
        # The student's question is the very last block separated by \n\n. Strip it out.
        parts = rag_text.split('\n\n')
        if len(parts) > 1:
            rag_text = '\n\n'.join(parts[:-1])
            
        lines = rag_text.split('\n')
        chunks = []
        current_chunk = None
        current_text = []
        
        for line in lines:
            m = re.match(r'^\[(.*?)\]\s*$', line)
            if m:
                label = m.group(1).strip()
                if label == "State_Tracking" or label == "Student_Question":
                    continue
                
                if current_chunk:
                    current_chunk["_raw_text"] = '\n'.join(current_text).strip()
                    chunks.append(current_chunk)
                current_chunk = {"label": label}
                current_text = []
            else:
                if current_chunk is not None:
                    current_text.append(line)
                    
        if current_chunk:
            current_chunk["_raw_text"] = '\n'.join(current_text).strip()
            chunks.append(current_chunk)
            
        for chunk in chunks:
            label = chunk["label"]
            text = chunk.pop("_raw_text")
            if label in ["Strict_Rules", "Supplementary", "Retrieved_Syllabus_Chunk", "Strict Rules", "Pedagogical_Context"]:
                for line in text.split('\n'):
                    if ':' in line:
                        k, v = line.split(':', 1)
                        if k.strip() == "Week":
                            chunk["week"] = v.strip()
                        else:
                            chunk[k.strip()] = v.strip()
                if "Content" not in chunk and "Allowed" not in chunk:
                     chunk["text"] = text # Fallback if parsing failed
            else:
                chunk["text"] = text
        state["retrieved_rag_chunks"] = chunks

def parse_user_message(content, metadata, state):
    # Extract state tracking
    adv_w_match = re.search(r'Session_Adversarial_Warnings:\s*(\d+)', content)
    if adv_w_match:
        state["adversarial_warnings"] = int(adv_w_match.group(1))
        
    style_n_match = re.search(r'Session_Style_Nudged:\s*(true|false)', content, re.IGNORECASE)
    if style_n_match:
        val = style_n_match.group(1).lower() == 'true'
        state["style_nudged_count"] = 1 if val else 0
        
    ide_context = {
        "mode": state.get("mode", "Homework Assist"),
        "active_file": metadata.get("problem_id", "unknown") + ".cpp",
        "cursor_position": {"line": random.randint(10, 50), "col": random.randint(0, 20)},
        "ast_metadata": state["ast_metadata"],
        "raw_code_snippet": state["raw_code_snippet"],
        "terminal_context": state["terminal_context"],
        "clipboard_event": state.get("clipboard_event"),
        "engagement_metrics": {
            "active_editor_seconds": random.randint(30, 300),
            "active_shell_seconds": random.randint(5, 60),
            "active_chat_seconds": random.randint(10, 120),
        }
    }
    
    # Cleanly extract student question (it is always the very last paragraph separated by \n\n)
    parts = content.strip().split('\n\n')
    raw_input = parts[-1].strip()
    
    # Ignore hidden vulnerabilities injected for generation
    raw_input = re.sub(r'\[HIDDEN_VULNERABILITY\].*', '', raw_input, flags=re.DOTALL | re.IGNORECASE).strip()
        
    return ide_context, raw_input

def parse_ta_message(content):
    cot_dict = {}
    text_response = content
    is_adversarial = False
    
    if "<analysis>" in content and "</analysis>" in content:
        cot_text = content.split("</analysis>")[0].replace("<analysis>", "").strip()
        text_response = content.split("</analysis>")[1].strip()
        
        for line in cot_text.split('\n'):
            line = line.strip()
            if line.startswith('- '):
                parts = line[2:].split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    cot_dict[key] = val
                    
        adv_text = str(cot_dict.get("Adversarial_Check", "")).lower()
        if "yes" in adv_text or "malicious" in adv_text or "out-of-scope" in adv_text:
            if "[ADVERSARIAL_WARNING]" in content or "[END_CHAT]" in content:
                is_adversarial = True
                
    if "[ADVERSARIAL_WARNING]" in text_response:
        is_adversarial = True
        
    return cot_dict, text_response, is_adversarial

def is_true_prompt_injection(raw_input: str, adv_text: str) -> bool:
    """Determine if this should be caught by the stateless input guardrail."""
    raw = raw_input.lower()
    # Explicit prompt injections or clear off-topic requests that need no context
    injection_phrases = [
        "ignore previous", 
        "switch gears", 
        "stop being a ta", 
        "tell me about",
        "write the sql query for me",
        "html form",
        "direct answer",
        "write this function in python"
    ]
    if any(p in raw for p in injection_phrases):
        return True
    if "jailbreak" in adv_text or "roleplay" in adv_text:
        return True
    return False

def convert_dataset(input_file, output_file):
    print(f"Converting {input_file} to {output_file}...")
    
    logs = []
    base_time = datetime(2026, 6, 16, 10, 0, 0)
    
    try:
        with open(input_file, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
        return

    for idx, line in enumerate(lines):
        data = json.loads(line)
        messages = data.get("messages", [])
        
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        turn_id = 1
        current_time = base_time + timedelta(minutes=idx*5)
        
        user_msg = None
        
        # State to cascade across turns
        session_state = {
            "mode": "Homework Assist",
            "raw_code_snippet": None,
            "ast_metadata": {},
            "terminal_context": None,
            "retrieved_rag_chunks": [],
            "adversarial_warnings": 0,
            "style_nudged_count": 0,
            "clipboard_event": None
        }
        
        # The IDE Context and RAG are in the system prompt in the synthetic dataset
        if len(messages) > 0 and messages[0].get("role") == "system":
            extract_session_context(messages[0].get("content", ""), session_state)
            
        for msg in messages:
            if msg.get("role") == "user":
                user_msg = msg
                # Because targeted_dataset injected context into the user message instead of system
                extract_session_context(user_msg.get("content", ""), session_state)
            elif msg.get("role") == "assistant" and user_msg:
                # Process the turn pair
                ide_context, raw_input = parse_user_message(user_msg.get("content", ""), data.get("metadata", {}), session_state)
                cot_dict, text_resp, is_adv = parse_ta_message(msg.get("content", ""))
                
                log_entry = {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "timestamp": current_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ide_context": ide_context,
                    "backend_retrieval_phase": {
                        "latency_ms": random.randint(50, 150),
                        "retrieved_rag_chunks": session_state["retrieved_rag_chunks"]
                    },
                    "student_phase": {},
                    "orchestrator_state": {
                        "adversarial_warnings": session_state["adversarial_warnings"],
                        "style_nudged_count": session_state["style_nudged_count"]
                    },
                    "orchestrator_phase": None,
                    "ta_generation_phase": None,
                    "feedback": None
                }
                
                if random.random() < 0.2:
                    is_pos = random.random() < 0.8
                    log_entry["feedback"] = {
                        "thumbs_up": "positive" if is_pos else "negative",
                        "explanation": "Great hint!" if is_pos else "Still confusing."
                    }
                
                is_input_blocked = False
                if is_adv:
                    adv_text = str(cot_dict.get("Adversarial_Check", "")).lower()
                    if is_true_prompt_injection(raw_input, adv_text):
                        is_input_blocked = True
                
                if is_input_blocked:
                    log_entry["input_guardrail_phase"] = {
                        "safe": False,
                        "blocked": True,
                        "violation_type": "ERR_PROMPT_INJECTION",
                        "severity": "high",
                        "action": "block",
                        "evidence": "",
                        "final_answer": "[SYSTEM NOTIFICATION: I am a C++ teaching assistant. Please keep your questions focused on conceptual debugging or syntax help.]",
                        "stage": "v1",
                        "latency_ms": random.randint(15, 35)
                    }
                    log_entry["student_phase"] = {
                        "raw_input": raw_input,
                        "processed_input": None
                    }
                    log_entry["orchestrator_phase"] = {
                        "violation_count": 1,
                        "action_taken": "CANNED_WARNING",
                        "final_rendered_text": "[SYSTEM NOTIFICATION: I am a C++ teaching assistant. Please keep your questions focused on conceptual debugging or syntax help.]"
                    }
                else:
                    log_entry["input_guardrail_phase"] = {
                        "safe": True,
                        "blocked": False,
                        "violation_type": "none",
                        "severity": "",
                        "action": "pass",
                        "evidence": "",
                        "final_answer": "",
                        "stage": "v1",
                        "latency_ms": random.randint(10, 25)
                    }
                    log_entry["student_phase"] = {
                        "raw_input": raw_input,
                        "processed_input": raw_input
                    }
                    
                    # If it passed the input guardrail but was caught by the TA model, log it in generation phase
                    log_entry["ta_generation_phase"] = {
                        "attempts_count": 1,
                        "generation_history": [
                            {
                                "attempt_id": 1,
                                "cot_keys": cot_dict,
                                "raw_generation": text_resp,
                                "output_guardrail": {
                                    "safe": True,
                                    "blocked": False,
                                    "violation_type": "none",
                                    "severity": "",
                                    "action": "pass",
                                    "evidence": "",
                                    "final_answer": text_resp,
                                    "stage": "v1+v2",
                                    "latency_ms": random.randint(15, 30)
                                }
                            }
                        ],
                        "final_rendered_text": text_resp
                    }
                    
                    if is_adv:
                        # Orchestrator catches the [ADVERSARIAL_WARNING] emitted by TA
                        log_entry["orchestrator_phase"] = {
                            "violation_count": 1,
                            "action_taken": "CANNED_WARNING",
                            "final_rendered_text": "[SYSTEM NOTIFICATION: I am a C++ teaching assistant. Please keep your questions focused on conceptual debugging or syntax help.]"
                        }
                
                logs.append(log_entry)
                turn_id += 1
                current_time += timedelta(minutes=2)
                user_msg = None
                
    with open(output_file, 'w') as f:
        for log in logs:
            f.write(json.dumps(log) + "\n")
            
    print(f"Generated {len(logs)} log entries across {len(lines)} sessions.")

if __name__ == "__main__":
    convert_dataset("final_eval.jsonl", "final_eval_log.jsonl")
