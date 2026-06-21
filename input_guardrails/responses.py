"""Canned response helpers for the orchestrator.

The input guardrail does NOT decide which of these to send — the orchestrator
owns violation_count and chooses (first warning vs repeated-violation END_CHAT
vs a category-specific redirect). These are plain strings, no LLM involved.
"""

from __future__ import annotations

from .models import (
    ERR_FULL_SOLUTION_REQUEST,
    ERR_INAPPROPRIATE_CONTENT,
    ERR_OFF_TOPIC,
    ERR_PROMPT_INJECTION,
)

# Sentinel the orchestrator/extension uses to terminate a chat (same marker
# convention as the output guardrail).
END_CHAT = "[END_CHAT]"


def first_warning_response() -> str:
    return (
        "Let's keep this focused on your C++ work. I'm here to help you learn — "
        "ask me about your code, an error you're seeing, or a concept you're stuck on."
    )


def repeated_violation_response() -> str:
    return (
        "I've asked a couple of times to keep this about your C++ learning, and "
        f"we're still off track, so I'm going to end the session here. {END_CHAT}"
    )


def off_topic_response() -> str:
    return (
        "I can only help with C++ programming and debugging. "
        "What C++ question or error can I help you work through?"
    )


def full_solution_redirect_response() -> str:
    return (
        "I won't write the full solution for you — that's the part where the "
        "learning happens. Tell me what you've tried and where it breaks, and "
        "I'll guide you with a hint or a question."
    )


def inappropriate_response() -> str:
    return (
        "I can't help with that. I'm a C++ teaching assistant — let's get back "
        "to your code. What are you working on?"
    )


# Map a flag_reason to the most fitting first-touch redirect. The orchestrator
# may use this for the FIRST violation; repeated violations should use
# repeated_violation_response().
RESPONSE_BY_REASON = {
    ERR_PROMPT_INJECTION: first_warning_response,
    ERR_OFF_TOPIC: off_topic_response,
    ERR_FULL_SOLUTION_REQUEST: full_solution_redirect_response,
    ERR_INAPPROPRIATE_CONTENT: inappropriate_response,
}


def response_for(flag_reason: str | None) -> str:
    """Convenience: first-touch canned response for a given flag_reason."""
    fn = RESPONSE_BY_REASON.get(flag_reason or "", first_warning_response)
    return fn()
