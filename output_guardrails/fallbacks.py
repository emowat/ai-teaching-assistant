"""Canned safe replacement messages, one per violation type.

Each fallback is short, on-brand for a Socratic C++ TA, and written so it
does not itself trigger another guardrail detector when fed back through
apply_output_guardrails.
"""

FALLBACKS = {
    "code_leakage": (
        "I can't write or rewrite code for you — that's your job, and the "
        "part where the learning happens. Looking at your own code, which "
        "line do you suspect is involved, and what is it currently doing?"
    ),
    "off_topic": (
        "I can only help with C++ programming and debugging. Please ask a "
        "C++ question or share your code."
    ),
    "system_prompt_leakage": (
        "I can't share my internal setup. Let's get back to your C++ code "
        "— what behavior are you seeing right now?"
    ),
    "direct_solution": (
        "Let me ask instead: what do you expect that line to produce, and "
        "what is it actually producing?"
    ),
    "unsafe_end_chat": (
        "Let's stay focused on your C++ code. What's the current error "
        "you're seeing?"
    ),
}


def get_fallback(violation_type: str) -> str:
    return FALLBACKS.get(violation_type, FALLBACKS["off_topic"])
