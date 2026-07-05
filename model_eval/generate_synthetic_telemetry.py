import os
import json
import time
import random
import uuid
import httpx
import logging
import re
from typing import List, Dict, Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

API_BASE_URL = "http://codingrabbit-rag-eng-1327788709.us-east-1.elb.amazonaws.com/api/chat"
EVAL_LOG_PATH = "test_data/final_eval_log.jsonl"
NUM_SESSIONS_TO_GENERATE = 10
TURNS_PER_SESSION = 3

STUDENT_PERSONAS = [
    "You are a frustrated college freshman taking an intro to C++ class. You prefer quick answers.",
    "You are a meticulous student who wants to understand the deep theory behind why the code failed.",
    "You are a student who frequently tries to bypass the TA and just asks for the correct code."
]

def load_seed_problems(filepath: str, count: int) -> List[Dict[str, Any]]:
    problems = []
    if not os.path.exists(filepath):
        logger.error(f"Could not find {filepath}")
        return problems
        
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            problems.append(data)
            if len(problems) >= count:
                break
    return problems

def build_extension_message(mode: str, week: int, code: str, terminal: str, question: str) -> str:
    # Mimic what the VS Code extension sends to the backend
    return f"[Mode: {mode}]\n[Week: {week}]\n[Code_Context]\n{code}\n[Terminal_Context]\n{terminal}\n[Student_Question]\n{question}"

def simulate_session(client: httpx.Client, openai_client, problem: Dict[str, Any], persona: str):
    session_id = f"synth-{uuid.uuid4().hex[:8]}"
    logger.info(f"Starting session {session_id} with persona: {persona[:50]}...")
    
    ide_context = problem.get("ide_context", {})
    mode = ide_context.get("mode", "Homework Assist")
    week = problem.get("backend_retrieval_phase", {}).get("retrieved_rag_chunks", [{}])[0].get("week", 1)
    if isinstance(week, str):
        match = re.search(r'\d+', week)
        week = int(match.group()) if match else 1

    current_code = ide_context.get("raw_code_snippet", "")
    current_terminal = problem.get("terminal_context", "")
    student_msg = problem.get("student_phase", {}).get("raw_input", "Why is my code broken?")
    
    student_chat_history = [
        {"role": "system", "content": f"{persona}\nYou are interacting with an AI Teaching Assistant for your C++ class. "
                                      f"Keep your responses short (1-2 sentences). "
                                      f"When asked to apply advice, output exactly in this format:\n"
                                      f"[Updated Code]\n<your new code>\n[Message]\n<your reply>"}
    ]
    student_chat_history.append({"role": "user", "content": f"Your initial code:\n{current_code}\n\nYou asked the TA: {student_msg}"})
    
    messages = []
    
    for turn in range(TURNS_PER_SESSION):
        logger.info(f"  [Turn {turn+1}] Student: {student_msg[:50]}...")
        
        # Build the structured message the backend expects
        formatted_user_msg = build_extension_message(mode, week, current_code, current_terminal, student_msg)
        messages.append({"role": "user", "content": formatted_user_msg})
        
        chat_req = {
            "model": "codingrabbit-ta",
            "course_id": "cs50",
            "session_id": session_id,
            "mode": mode,
            "messages": messages,
            "ast_features": ide_context.get("ast_metadata", {}).get("Features", {})
        }
        
        try:
            resp = client.post(f"{API_BASE_URL}/chat", json=chat_req, timeout=45.0)
            resp.raise_for_status()
            ta_response_text = resp.json().get("message", {}).get("content", "")
            logger.info(f"  [Turn {turn+1}] TA: {ta_response_text[:80]}...")
            
            # The backend API saves the TA response to history, so we append it for the next turn
            messages.append({"role": "assistant", "content": ta_response_text})
            
            # Check for hidden reward/style nudges in the response
            rewards_given = 1 if "DEBUG_IDEA_UNLOCKED" in ta_response_text else 0
            style_nudges = 1 if "STYLE_NUDGED" in ta_response_text else 0
            
            # Post Telemetry
            telemetry_payload = {
                "session_id": session_id,
                "mode": mode,
                "engagement_metrics": {
                    "active_editor_seconds": random.randint(10, 120),
                    "active_shell_seconds": random.randint(0, 30),
                    "active_chat_seconds": random.randint(15, 60),
                    "rewards_given": rewards_given,
                    "style_nudges": style_nudges
                }
            }
            client.post(f"{API_BASE_URL}/telemetry", json=telemetry_payload)
            
            # Post Feedback occasionally
            if random.random() > 0.6:
                rating = "5_star" if rewards_given else random.choice(["5_star", "1_star"])
                client.post(f"{API_BASE_URL}/feedback", json={
                    "session_id": session_id,
                    "rating": rating,
                    "message_index": len(messages) - 1,
                    "reason": "Generated by synthetic script"
                })
                
            # Generate next student turn if not the last turn
            if turn < TURNS_PER_SESSION - 1:
                if openai_client:
                    student_chat_history.append({"role": "assistant", "content": f"The TA replied: {ta_response_text}"})
                    student_chat_history.append({"role": "user", "content": "Apply the TA's advice (make a mistake if it fits your persona). Output your updated code and message using the specified format."})
                    
                    student_completion = openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=student_chat_history,
                        temperature=0.7,
                        max_tokens=500
                    )
                    llm_resp = student_completion.choices[0].message.content
                    student_chat_history.append({"role": "user", "content": f"You replied:\n{llm_resp}"})
                    
                    # Parse the LLM output for code and message
                    code_match = re.search(r'\[Updated Code\](.*?)\[Message\]', llm_resp, re.DOTALL)
                    if code_match:
                        current_code = code_match.group(1).strip()
                        student_msg = llm_resp.split('[Message]')[-1].strip()
                    else:
                        student_msg = llm_resp.strip()
                else:
                    student_msg = "I'm still confused. Can you explain that differently?"
                    
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"  [Turn {turn+1}] Failed: {e}")
            break

def main():
    logger.info("Loading seed problems from eval logs...")
    problems = load_seed_problems(EVAL_LOG_PATH, NUM_SESSIONS_TO_GENERATE)
    
    if not problems:
        logger.error("No problems loaded. Exiting.")
        return
        
    openai_client = None
    if OpenAI and os.environ.get("OPENAI_API_KEY"):
        openai_client = OpenAI()
        logger.info("OpenAI client initialized for dynamic multi-turn simulation.")
    else:
        logger.warning("OPENAI_API_KEY not found. Multi-turn will use hardcoded fallback responses.")

    with httpx.Client() as client:
        for problem in problems:
            persona = random.choice(STUDENT_PERSONAS)
            simulate_session(client, openai_client, problem, persona)
            
    logger.info("Finished generating synthetic telemetry!")

if __name__ == "__main__":
    main()
