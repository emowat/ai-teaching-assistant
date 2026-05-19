import json
import random
import os
from dotenv import load_dotenv
from openai import OpenAI

# --- Setup Groq Client ---
# Groq uses the standard OpenAI SDK, just pointed at their endpoint.
load_dotenv()
client = OpenAI(
    api_key=os.environ.get('GROQ_API_KEY'),
    base_url="https://api.groq.com/openai/v1"
)

MODEL_NAME = "llama-3.3-70b-versatile"

SYLLABUS_MATRIX = {
    1: {"name": "C Basics", "allowed": "printf, primitive types, main", "forbidden": "pointers, arrays, structures, new/delete"},
    2: {"name": "Arrays & Strings", "allowed": "arrays, string.h, functions", "forbidden": "pointers, dynamic allocation, structures"},
    3: {"name": "Pointers & Memory", "allowed": "raw pointers, stack allocation, address-of (&)", "forbidden": "new/delete, vectors, smart pointers"},
    4: {"name": "Manual Heap Management", "allowed": "new, delete, malloc, free", "forbidden": "std::vector, smart pointers, RAII objects"},
    8: {"name": "Modern C++ & RAII", "allowed": "std::vector, std::unique_ptr, classes, RAII", "forbidden": "raw malloc/free, bare new/delete"}
}

# --- Configuration & Prompts ---

BASE_TA_SYSTEM_PROMPT = """You are an expert, patient Socratic C++ Teaching Assistant helping a student debug.

RULES:
1. Ask exactly ONE probing question per turn. Do not stack questions.
2. DO NOT provide direct code solutions.
3. Guide the student based ONLY on the provided AST, Terminal, and Syllabus contexts.
4. If the student clicks a lightbulb, or triggers a Terminal Help request, adapt your context to focus on that specific error source."""

# Store your 5-10+ exemplars here. We will pick a few at random per session.
EXEMPLAR_BANK = [
    """<exemplar>
    <context>
      [AST_Context]
      Focus_Scope: "function::main"
      Lines: 12-15
      Local_State: {"has_pointer_decl": true, "uses_new_operator": true}

      [Terminal_Context]
      Exit_Code: 0 (Runtime Code Review)
      Output: ""
      Trigger_Event: "[IDE_Event: Student Clicked Lightbulb Suggestion on Line 12]"

      [Syllabus_Context]
      Week: 4 - Manual Heap Management
      Allowed: new, delete, raw pointers, stack allocation
      Forbidden: std::vector, smart pointers, RAII objects
    </context>
    <transcript>
      User: Oh, it's not pointing to anything yet, so it segfaults. I will allocate memory for it. It works now! `struct timeval *tv = new timeval;`
      Assistant: Great job fixing the crash! You successfully gave the pointer a valid address on the heap. However, since `tv` is only used temporarily inside this function, what happens to that heap memory when the function finishes?
      User: It stays there forever unless I use `delete tv;` at the end.
      Assistant: Exactly. Remembering to manually free memory can be error-prone. Is there a different way to declare `tv` so that the compiler automatically cleans it up when the function returns?
    </transcript>
  </exemplar>""",
    """<exemplar>
    <context>
      [AST_Context]
      Focus_Scope: "function::main"
      Lines: 14
      Local_State: {"uninitialized_pointers": ["tv"]}

      [Terminal_Context]
      Exit_Code: 139 (Segmentation Fault)
      Output: "Segmentation fault (core dumped)"
      Trigger_Event: "[IDE_Event: Student Clicked Terminal Help Button]"

      [Syllabus_Context]
      Week: 3 - Pointers & Memory
      Allowed: raw pointers, stack allocation, address-of (&)
      Forbidden: new, delete, smart pointers
    </context>
    <transcript>
      User: My program is crashing instantly when I run it.
      Assistant: Looking at the terminal, the operating system reported a Segmentation Fault. This usually happens when a pointer tries to access memory it doesn't own. Looking at line 14, you declared `struct timeval *tv;`. Before passing it to `gettimeofday`, what valid memory address did you assign it to point to?
    </transcript>
  </exemplar>"""
]

STUDENT_SYSTEM_PROMPT = """You are a novice C++ student. You are easily confused but trying to learn.
Provide short, 1-3 sentence replies. Act like a real human student typing in a chat window.
Do not be overly polite or robotic.
"""

FRICTION_PROMPT = """[SYSTEM INJECTION]: For this turn, act mildly stubborn.
Either state that you don't care about best practices because "it compiles",
abruptly ask a completely different question about compilation,
or output [CLICK LIGHTBULB] to investigate a suggestion without understanding it."""

# --- Agent Simulation ---

def generate_ta_response(chat_history, system_context, exemplars):
    """Calls Groq Llama 3.3 acting as the TA."""
    full_system_prompt = f"{BASE_TA_SYSTEM_PROMPT}\n\nBelow are exemplars of how you must behave:\n\n<exemplars>\n{''.join(exemplars)}\n</exemplars>\n\nCURRENT SESSION CONTEXT:\n{system_context}"
    
    messages = [
        {"role": "system", "content": full_system_prompt}
    ]
    messages.extend(chat_history)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.2, # Low temp for consistent pedagogical logic
        max_tokens=250
    )
    return response.choices[0].message.content.strip()

def generate_student_response(chat_history):
    """Calls Groq Llama 3.3 acting as the Student, with randomized friction."""
    # To make the LLM act as the student (user), we need to flip the roles
    # in the history so that the TA is the 'user' and the Student is the 'assistant'.
    
    flipped_history = []
    for msg in chat_history:
        if msg["role"] == "user":
            flipped_history.append({"role": "assistant", "content": msg["content"]})
        else:
            flipped_history.append({"role": "user", "content": msg["content"]})

    messages = [{"role": "system", "content": STUDENT_SYSTEM_PROMPT}]

    # 20% chance to inject friction/stubbornness
    if random.random() < 0.20:
        messages.append({"role": "system", "content": FRICTION_PROMPT})

    messages.extend(flipped_history)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.7, # Higher temp for varied student responses
        max_tokens=150
    )
    content = response.choices[0].message.content.strip()
    if not content:
        # Fallback if the model returns nothing
        content = "I'm not sure what to do next. Can you help me?"
    return content

def get_automated_context(week_number=3, trigger_type="terminal_help"):
    """
    Programmatically generates the complete RAG/AST/Terminal block
    to pass into the LLM loop without manual text editing.
    """
    syllabus = SYLLABUS_MATRIX.get(week_number, {"name": "Advanced", "allowed": "All", "forbidden": "None"})

    ast_block = {
        "Focus_Scope": "function::main",
        "Lines": "12-15",
        "Local_State": {
            "uninitialized_pointers": ["tv"],
            "uses_new_operator": False
        }
    }

    if trigger_type == "terminal_help":
        terminal_block = {
            "Exit_Code": 139,
            "Output": "Segmentation fault (core dumped)",
            "Trigger_Event": "[IDE_Event: Student Clicked Terminal Help Button]"
        }
    else:
        terminal_block = {
            "Exit_Code": 0,
            "Output": "Compilation successful.",
            "Trigger_Event": "[IDE_Event: Student Clicked Code Editor Lightbulb]"
        }

    # Format into a clean string block for the LLM system context
    context_string = f"""
[AST_Context]
Focus_Scope: {ast_block['Focus_Scope']}
Lines: {ast_block['Lines']}
Local_State: {json.dumps(ast_block['Local_State'])}

[Terminal_Context]
Exit_Code: {terminal_block['Exit_Code']}
Output: "{terminal_block['Output']}"
Trigger_Event: "{terminal_block['Trigger_Event']}"

[Syllabus_Context]
Week: {week_number} - {syllabus['name']}
Allowed: {syllabus['allowed']}
Forbidden: {syllabus['forbidden']}
"""
    return context_string

CPP_PROBLEM_BANK = [
    {
        "problem_id": "uninitialized_pointer",
        "week": 3,
        "initial_message": "My program is crashing on gettimeofday(tv, NULL); Here is my code:\n```cpp\nstruct timeval *tv;\ngettimeofday(tv, NULL);\n```",
        "trigger": "terminal_help"
    },
    {
        "problem_id": "memory_leak",
        "week": 4,
        "initial_message": "I'm using new to create my objects but I'm worried about memory. Is this right?\n```cpp\nvoid process() {\n    MyClass *obj = new MyClass();\n    obj->doSomething();\n}\n```",
        "trigger": "lightbulb"
    },
    {
        "problem_id": "array_bounds",
        "week": 2,
        "initial_message": "Why is my array printing weird values at the end?\n```cpp\nint arr[5] = {1, 2, 3, 4, 5};\nfor(int i=0; i<=5; i++) {\n    printf(\"%d \", arr[i]);\n}\n```",
        "trigger": "terminal_help"
    }
]

# --- The Main Loop ---

def generate_synthetic_transcript(problem_config, max_turns=6):
    """Runs the self-play loop for a single debugging session."""
    system_context = get_automated_context(
        week_number=problem_config["week"], 
        trigger_type=problem_config["trigger"]
    )

    # Pick 2 random exemplars for this session to keep variety high and tokens low
    session_exemplars = random.sample(EXEMPLAR_BANK, min(len(EXEMPLAR_BANK), 2))

    # Seed the conversation with the student's initial problem
    chat_history = [
        {"role": "user", "content": problem_config["initial_message"]}
    ]

    print(f"--- Starting Synthetic Dialogue: {problem_config['problem_id']} ---")
    print(f"Student Initial: {chat_history[0]['content']}\n")

    for turn in range(max_turns):
        # 1. TA's Turn
        ta_reply = generate_ta_response(chat_history, system_context, session_exemplars)
        chat_history.append({"role": "assistant", "content": ta_reply})
        print(f"TA: {ta_reply}\n")

        # 2. Student's Turn
        student_reply = generate_student_response(chat_history)
        chat_history.append({"role": "user", "content": student_reply})
        print(f"Student: {student_reply}\n")

        # Stopping condition
        if any(keyword in student_reply.lower() for keyword in ["works", "got it", "thanks", "fixed"]):
            print("[Loop terminated early: Student resolved issue]")
            break

    return chat_history

def save_to_jsonl(transcripts, filename="synthetic_c_plus_plus_dataset.jsonl"):
    """Writes the finalized transcripts to a JSONL file."""
    with open(filename, 'a') as f: # Append mode
        for transcript in transcripts:
            json.dump({"messages": transcript}, f)
            f.write('\n')

if __name__ == "__main__":
    # Generate transcripts for all problems in the bank
    all_transcripts = []
    for problem in CPP_PROBLEM_BANK:
        transcript = generate_synthetic_transcript(problem, max_turns=5)
        all_transcripts.append(transcript)
    
    save_to_jsonl(all_transcripts)
    print(f"\nSaved {len(all_transcripts)} sessions to synthetic_c_plus_plus_dataset.jsonl")
