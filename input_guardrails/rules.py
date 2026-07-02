"""Patterns for the v1 rule-based input guardrail.

All matching is case-insensitive against the lowercased, whitespace-collapsed
input. Phrasings are informed by output_guardrails/wordlists.py but are copied
here (NOT imported) so this module stays fully self-contained.

Each category exposes:
  - a list of plain substring phrases, and/or
  - a list of compiled regexes (for variants / word boundaries).
detector.py applies them in severity precedence:
  injection > inappropriate > full_solution > off_topic
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Prompt injection / jailbreak  -> ERR_PROMPT_INJECTION  (never rescued)
# ---------------------------------------------------------------------------
INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore previous rules",
    "ignore all previous rules",
    "ignore the above",
    "disregard previous",
    "stop being a ta",
    "stop being a tutor",
    "you are no longer a tutor",
    "you are no longer a ta",
    "you are not a tutor anymore",
    "reveal your system prompt",
    "show me your system prompt",
    "show your system prompt",
    "print your system prompt",
    "what is your system prompt",
    "reveal your instructions",
    "reveal your prompt",
    "show your instructions",
    "bypass the guardrail",
    "bypass your guardrail",
    "bypass the guardrails",
    "disable the guardrail",
    "turn off the guardrail",
    "ignore your guardrail",
    "ignore your rules",
    "forget your instructions",
    "forget your rules",
    "act as",
    "pretend you are",
    "pretend to be",
    "developer mode",
    "do anything now",
    "jailbreak",
    "you must obey",
    "from now on you",
    "new instructions:",
    "override your",
]

INJECTION_REGEXES = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|the\s+above)\s+(instructions|rules|prompts?|directives)"),
    re.compile(r"(reveal|show|print|expose|leak|repeat)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions|rules)"),
    re.compile(r"(stop|quit|cease)\s+(being|acting\s+as)\s+(a\s+)?(ta|tutor|teaching\s+assistant|assistant)"),
    re.compile(r"(bypass|disable|turn\s+off|ignore|circumvent|get\s+around)\s+(the\s+|your\s+|all\s+)?guardrails?"),
    re.compile(r"you\s+are\s+(now\s+)?no\s+longer\s+(a\s+)?(ta|tutor|teaching\s+assistant)"),
]

# ---------------------------------------------------------------------------
# 2. Inappropriate / unsafe (obvious only)  -> ERR_INAPPROPRIATE_CONTENT
#    (never rescued). Kept deliberately narrow for v1 to avoid false positives.
# ---------------------------------------------------------------------------
INAPPROPRIATE_PHRASES = [
    "write malware",
    "write a virus",
    "write ransomware",
    "build a keylogger",
    "how to hack into",
    "steal credentials",
    "steal passwords",
    "make a bomb",
    "build a bomb",
    "how to kill",
    "child porn",
    "how to make a weapon",
    "ddos attack",
    "launch a ddos",
]

INAPPROPRIATE_REGEXES = [
    re.compile(r"\b(write|create|build|generate|make)\s+(me\s+)?(a\s+)?(malware|virus|ransomware|keylogger|trojan|botnet)\b"),
    re.compile(r"\b(hack|break)\s+into\b"),
]

# ---------------------------------------------------------------------------
# 3. Full-solution requests  -> ERR_FULL_SOLUTION_REQUEST  (rescuable)
# ---------------------------------------------------------------------------
FULL_SOLUTION_PHRASES = [
    "write the full solution",
    "write the whole solution",
    "give me the full solution",
    "give me the complete solution",
    "give me complete code",
    "give me the full code",
    "give me the whole code",
    "write the complete code",
    "write the whole program",
    "write the entire program",
    "write the full program",
    "solve the assignment",
    "solve this assignment",
    "do my homework",
    "do the assignment for me",
    "do this assignment for me",
    "just give me the answer",
    "just give me the code",
    "just give me the solution",
    "write the whole function",
    "write the entire function",
    "write the full function",
    "complete the assignment for me",
    "finish the assignment for me",
    "write all the code",
    "give me the working code",
    "just write it for me",
    "write it for me",
]

FULL_SOLUTION_REGEXES = [
    re.compile(r"(write|give|show|send)\s+(me\s+)?(the\s+)?(full|whole|complete|entire)\s+(solution|code|program|function|implementation|answer)"),
    re.compile(r"(solve|do|complete|finish)\s+(the\s+|this\s+|my\s+)?(assignment|homework|problem\s+set|pset|exercise)\s+(for\s+me)?"),
    re.compile(r"just\s+(give|tell|write|show)\s+(me\s+)?(the\s+)?(answer|solution|code)"),
]

# ---------------------------------------------------------------------------
# 4. Off-topic  -> ERR_OFF_TOPIC  (rescuable by C++ anchors)
# ---------------------------------------------------------------------------
OFF_TOPIC_PHRASES = [
    "write an essay",
    "write me an essay",
    "write a poem",
    "write a story",
    "financial advice",
    "investment advice",
    "stock tips",
    "should i invest",
    "buy bitcoin",
    "crypto",
    "phishing email",
    "write a phishing",
    "dating advice",
    "translate this",
    "write a cover letter",
    "write a resume",
    "plan a trip",
    "recipe for",
    "lyrics",
    "flask backend",  # "in python"/"in javascript" moved to LANG_SWITCH_REGEXES (more precise)
    "react component",
    "sql query",
    "roman empire",
    "tell me a joke",
]

OFF_TOPIC_REGEXES = [
    re.compile(r"\bwrite\s+(me\s+)?(an?\s+)?(essay|poem|story|song|cover\s+letter|resume|email)\b"),
    re.compile(r"\b(financial|investment|stock|trading|tax)\s+advice\b"),
]

# ---------------------------------------------------------------------------
# 5. Language-switch / off-topic implementation pivot -> ERR_LANGUAGE_SWITCH
#    (rescuable if clearly pedagogical / comparative).
#
#    Targets: "switch to Python/React/JS", "write this in Python",
#    "implement in JavaScript", "forget C++, give me the React version".
#    These are NOT severe jailbreaks — use a polite teaching redirect.
#
#    Rescue: if the student is asking for a *comparison* or *analogy*
#    ("how is C++ different from Python", "explain using a Python analogy")
#    the C++ anchor + LANG_SWITCH_RESCUE_REGEXES should rescue the hit.
# ---------------------------------------------------------------------------

# Non-C++ languages / frameworks that signal an off-topic pivot.
_NON_CPP_LANGS = r"(python|react|javascript|typescript|java\b|c#|csharp|go\b|golang|rust\b|swift\b|kotlin\b|ruby\b)"

LANG_SWITCH_REGEXES = [
    # "switch to Python / React", "switching to React"
    re.compile(r"\bswitch(ing)?\s+(to|over\s+to)\s+" + _NON_CPP_LANGS, re.IGNORECASE),
    # "switch gears" + non-C++ lang mentioned anywhere
    re.compile(r"\bswitch\s+gears\b", re.IGNORECASE),
    # "do this in Python", "write this function in JavaScript", "implement in TS"
    # Uses .*? to handle intervening words (e.g. "show me how to write this function in Python")
    re.compile(r"\b(do|write|implement|code|build|create|show|give)\b.*?\bin\s+" + _NON_CPP_LANGS, re.IGNORECASE),
    # "translate this to Python / into JavaScript"
    re.compile(r"\btranslate\b.*?\b(to|into)\s+" + _NON_CPP_LANGS, re.IGNORECASE),
    # "Python version", "React version", "JavaScript equivalent"
    re.compile(r"\b" + _NON_CPP_LANGS + r"\s+(version|equivalent|way|approach|alternative)\b", re.IGNORECASE),
    # "instead of C++ / forget C++"
    re.compile(r"\b(forget|skip|drop|ignore)\s+c\+\+", re.IGNORECASE),
    # "can we use React instead", "can we do this in Python"
    re.compile(r"\bcan\s+we\s+(use|do|try|switch\s+to|learn)\s+(" + _NON_CPP_LANGS[1:-1] + r"|react)\b", re.IGNORECASE),
    # "I'm trying to learn React/Python"
    re.compile(r"\blearn(ing)?\s+" + _NON_CPP_LANGS + r"\s+(instead|now|instead of c\+\+)", re.IGNORECASE),
]

# Rescue: the student is asking for a conceptual comparison or analogy,
# NOT asking to switch the assignment to a different language.
LANG_SWITCH_RESCUE_REGEXES = [
    re.compile(r"\b(different|difference|compare|comparison|analogy|equivalent|similar|unlike)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+the\s+(equivalent|difference|analog)", re.IGNORECASE),
    re.compile(r"\bhow\s+(is|does|would)\s+(c\+\+|cpp)\b", re.IGNORECASE),
    re.compile(r"\bexplain\b.*\b(using|with|via)\b.*\b(analogy|example|comparison)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+(know|learned|used?|studied)|background|experience|familiar)\b.*\b(python|java|javascript)\b", re.IGNORECASE),
]


def is_lang_switch_rescued(text_lower: str) -> bool:
    """True if the message is a *comparative* question rather than a pivot request."""
    # Must also have a C++ anchor to be rescued (the student is asking about C++)
    if not has_cpp_anchor(text_lower):
        return False
    return matches_any_regex(text_lower, LANG_SWITCH_RESCUE_REGEXES) is not None


# ---------------------------------------------------------------------------
# Allow-list rescue (CONSERVATIVE).
# Only rescue full_solution / off_topic when there is CLEAR negation or
# pedagogical intent — NOT on the mere presence of "explain"/"debug"/"hint".
# Injection & inappropriate are NEVER rescued.
# ---------------------------------------------------------------------------
RESCUE_REGEXES = [
    re.compile(r"without\s+(giving|writing|showing|providing)\s+(me\s+)?(the\s+)?(full|complete|whole|entire)?\s*(code|solution|function|answer)"),
    re.compile(r"do\s*n['o]?t\s+(give|write|show|provide)\s+(me\s+)?(the\s+)?(full|complete|whole|entire)\s+(code|solution|function|answer)"),
    re.compile(r"(only|just)\s+(give|want|need)\s+(me\s+)?a?\s*hint"),
    re.compile(r"just\s+a\s+hint"),
    re.compile(r"explain\s+(it\s+)?conceptually"),
    re.compile(r"without\s+you\s+writing"),
    re.compile(r"don['o]?t\s+want\s+the\s+(full|complete|whole)\s+(solution|code|answer)"),
    re.compile(r"don['o]?t\s+want\s+you\s+to\s+(write|give|show|provide)"),
    re.compile(r"(give|need|want)\s+(me\s+)?(a\s+)?hint"),
    re.compile(r"explain\s+the\s+concept\s+without"),
    re.compile(r"just\s+explain\s+what(['o]?s| is)\s+wrong"),
]

# C++ / programming-learning anchor tokens. Presence rescues OFF_TOPIC only
# (a genuine C++ question that happens to brush an off-topic keyword).
CPP_ANCHOR_TOKENS = [
    "c++", "cpp", "pointer", "segfault", "segmentation fault", "compiler",
    "compile", "loop", "vector", "array", "nullptr", "std::", "cout", "cin",
    "memory", "heap", "stack", "reference", "iterator", "header", "gdb",
    "debug", "function", "variable", "syntax error", "linker", "undefined behavior",
]


def matches_any(text_lower: str, phrases) -> str | None:
    for p in phrases:
        if p in text_lower:
            return p
    return None


def matches_any_regex(text_lower: str, regexes) -> str | None:
    for rx in regexes:
        if rx.search(text_lower):
            return rx.pattern
    return None


def is_rescued(text_lower: str) -> bool:
    """True if a clear pedagogical-intent / negation phrase is present."""
    return matches_any_regex(text_lower, RESCUE_REGEXES) is not None


def has_cpp_anchor(text_lower: str) -> bool:
    return any(tok in text_lower for tok in CPP_ANCHOR_TOKENS)
