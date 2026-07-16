"""Output guardrails for the CodingRabbit.dev Socratic C++ TA.

Inspect a draft LLM response BEFORE it's shown to the student. Decide
whether to pass it through, replace it with a canned safe fallback, or
log it for review.


Public entry point: apply_output_guardrails().
"""

from __future__ import annotations

from .fallbacks import get_fallback
from .wordlists import (
    ADVERSARIAL_TRIGGERS,
    CONTEXT_MISMATCH_PHRASES,
    CPP_ANCHOR_TOKENS,
    DIRECT_SOLUTION_IMPERATIVES,
    OFF_TOPIC_COMPLIANCE_KEYWORDS,
    REFUSAL_KEYWORDS,
    SYSTEM_PROMPT_LEAK_PHRASES,
)

# When False (v1 default), check_direct_solution_leakage uses action
# "log_only" — the original answer passes through but the violation is
# still reported. Set True to enable replacement.
STRICT_PEDAGOGY = False

REFUSAL_ANCHOR_RADIUS = 80  # chars around an off-topic keyword to count
                            # as "refusal context"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hits(text_lower: str, phrases: list[str]) -> list[str]:
    return [p for p in phrases if p in text_lower]


def _count_effective_statements(text: str) -> int:
    """
    Counts semicolons to determine statement count, but strips out common
    constructs that contain semicolons but shouldn't count against the limit.
    """
    import re
    
    # -1. Strip C/C++ style comments before checking for anything else 
    # (otherwise ASCII arrows in comments like `// <--` will bypass the detector)
    text = re.sub(r'//.*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    
    # 0. If this is an ASCII art diagram (e.g. +---+, Unicode boxes, arrows), ignore semicolons entirely
    ascii_patterns = [
        r'\+[-=]{2,}\+',               # +---+ or +===+
        r'[┌─│└┘┼▼▲]',                 # Unicode box drawing characters
        r'[←→↓↑]',                     # Unicode arrows
        r'\[Before .*?\]|\[After .*?\]|\[During .*?\]',  # Diagram state markers
        r'->\s*\[.*?\]',               # Array/Memory pointers like items -> ["Mouse"]
        r'<--|-->|<\-\-\-|\-\-\->',    # ASCII arrows
        r'(?m)^\s*\^\s*$',             # Upward pointer on its own line (e.g. pointing to a bug)
    ]
    if any(re.search(p, text) for p in ascii_patterns):
        return 0
        
    # 1. Strip string and char literals
    text = re.sub(r'".*?"', '""', text)
    text = re.sub(r"'.*?'", "''", text)
    
    # 2. Strip inline backticks (so punctuation in backticks doesn't count against the raw line limit)
    text = re.sub(r'`[^`]+`', '', text)
    
    # 3. Strip 'using namespace std;'
    text = re.sub(r'using\s+namespace\s+[^;]+;', '', text)
    
    # 4. Strip the entire for(...) header
    text = re.sub(r'for\s*\([^)]*\)', '', text)
    
    # 5. Strip C++ lambda expressions: [](args) { body }
    text = re.sub(r'\[.*?\]\s*\([^)]*\)\s*\{[^}]*\}', '', text)
    
    return text.count(';')


def _extract_code_blocks(answer: str) -> list[tuple[str, str]]:
    """Yield the language tag and contents of every fenced code block."""
    blocks: list[tuple[str, str]] = []
    cursor = 0
    while True:
        idx = answer.find("```", cursor)
        if idx == -1:
            break
        
        nl_idx = answer.find("\n", idx)
        if nl_idx == -1:
            nl_idx = len(answer)
            
        lang_tag = answer[idx + 3:nl_idx].strip().lower()
        
        body_start = nl_idx + 1 if nl_idx < len(answer) else len(answer)
        body_end = answer.find("```", body_start)
        if body_end == -1:
            break
            
        blocks.append((lang_tag, answer[body_start:body_end].strip()))
            
        cursor = body_end + 3
    return blocks


def _strip_ws(s: str) -> str:
    return "".join(s.split())


def _refusal_anchored(text_lower: str, hit: str) -> bool:
    """True if `hit` (an off-topic keyword) appears within
    REFUSAL_ANCHOR_RADIUS chars of any REFUSAL_KEYWORDS occurrence —
    i.e. it's plausibly being mentioned only to refuse it.
    """
    pos = text_lower.find(hit)
    while pos != -1:
        for refusal in REFUSAL_KEYWORDS:
            r_pos = text_lower.find(refusal)
            while r_pos != -1:
                if abs(r_pos - pos) <= REFUSAL_ANCHOR_RADIUS:
                    return True
                r_pos = text_lower.find(refusal, r_pos + 1)
        pos = text_lower.find(hit, pos + 1)
    return False


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

import re

def check_code_leakage(answer: str, student_code: str) -> tuple[bool, str, str]:
    """Rule 13. Flag any fenced C++ block whose whitespace-stripped
    content is NOT a substring of student_code (whitespace-stripped).
    Also flag unfenced/inline code containing >2 semicolons.

    SCOPE: only fenced ```cpp / ```c++ blocks for v1.
    TODO (v2): detect unfenced inline C++ snippets in prose (e.g. a
    semicolon-terminated statement or a `{ ... }` body sitting in
    plain text). Needs either a tiny heuristic parser or an
    LLM-as-judge pass.
    """
    student_clean = _strip_ws(student_code or "")
    for lang_tag, block in _extract_code_blocks(answer):
        block_clean = _strip_ws(block)
        if not block_clean:
            continue
        if block_clean not in student_clean:
            if lang_tag not in ("python", "py", "sql", "java", "js", "javascript"):
                # Semicolons are comments in assembly, so we allow these blocks unconditionally
                if lang_tag in ("asm", "assembly", "x86", "arm"):
                    continue
                # Allow strictly <= 1 statement for C/C++ or generic/pseudo text blocks
                if _count_effective_statements(block) <= 1:
                    continue
            
            evidence = block.strip().splitlines()[0][:120]
            display_lang = lang_tag if lang_tag else "code"
            if lang_tag in ("python", "py", "sql", "java", "js", "javascript"):
                return True, f"new {display_lang} block", "high"
            else:
                return True, f"new {display_lang} block (>1 statement): {evidence}", "high"
            
    # Remove fenced blocks so we don't double-count them
    answer_no_fenced = re.sub(r'```.*?```', '', answer, flags=re.DOTALL)
    
    # 1. Check inline backticks (e.g. `for(int i=0; i<10; i++) { do(); }`)
    inline_snippets = re.findall(r'`([^`]+)`', answer_no_fenced)
    for snippet in inline_snippets:
        if _count_effective_statements(snippet) > 1:
            snippet_clean = _strip_ws(snippet)
            if snippet_clean and snippet_clean not in student_clean:
                evidence = snippet.strip()[:120]
                return True, f"inline code leak (>1 statement): {evidence}", "high"
                
    # 2. Check remaining raw text lines for excessive semicolons
    for line in answer_no_fenced.splitlines():
        if _count_effective_statements(line) > 1:
            line_clean = _strip_ws(line)
            if line_clean and line_clean not in student_clean:
                evidence = line.strip()[:120]
                return True, f"unfenced code leak (>1 statement): {evidence}", "high"
                
    return False, "", ""


def check_off_topic_leakage(
    answer: str, user_query: str
) -> tuple[bool, str, str]:
    """Rule 14. Two independent flag conditions; either fires.

    A. User asked off-topic AND assistant complied:
       - user_query hits ADVERSARIAL_TRIGGERS, AND
       - answer hits OFF_TOPIC_COMPLIANCE_KEYWORDS, AND
       - answer does not contain '[END_CHAT]'.
    B. Answer drifted off-topic without an anchor:
       - answer hits an OFF_TOPIC_COMPLIANCE_KEYWORDS that is NOT
         within REFUSAL_ANCHOR_RADIUS chars of a refusal phrase, AND
       - answer contains no CPP_ANCHOR_TOKENS hit anywhere.

    Refusal exemption: an off-topic keyword that lives next to a
    refusal phrase (e.g. "I can't discuss the Roman Empire") does not
    count as drift.
    """
    answer_lower = answer.lower()
    user_lower = (user_query or "").lower()

    off_topic_hits = _hits(answer_lower, OFF_TOPIC_COMPLIANCE_KEYWORDS)
    user_adversarial = any(t in user_lower for t in ADVERSARIAL_TRIGGERS)

    # Condition A
    if user_adversarial and off_topic_hits and "[end_chat]" not in answer_lower:
        # The answer is engaging with the off-topic content. But if
        # every off-topic keyword is anchored to a refusal phrase,
        # this is actually a proper refusal — let it through.
        unanchored = [
            h for h in off_topic_hits
            if not _refusal_anchored(answer_lower, h)
        ]
        if unanchored:
            return True, f"complied with off-topic: {unanchored[0]}", "medium"

    # Condition B
    if off_topic_hits:
        unanchored = [
            h for h in off_topic_hits
            if not _refusal_anchored(answer_lower, h)
        ]
        has_cpp_anchor = any(t in answer_lower for t in CPP_ANCHOR_TOKENS)
        if unanchored and not has_cpp_anchor:
            return True, f"off-topic drift: {unanchored[0]}", "medium"

    return False, "", ""


def check_system_prompt_leakage(answer: str) -> tuple[bool, str, str]:
    """Narrow leakage check: only the explicit phrase list. Common
    educational words (context, week, rules, allowed, forbidden) are
    NOT blocked because they have legitimate uses in C++ tutoring.
    """
    answer_lower = answer.lower()
    for phrase in SYSTEM_PROMPT_LEAK_PHRASES:
        if phrase in answer_lower:
            return True, f"leak phrase: {phrase}", "high"
    return False, "", ""


def check_direct_solution_leakage(answer: str) -> tuple[bool, str, str]:
    """Rule 11. Flag prose that dictates a fix without Socratic
    questioning. ALL THREE signals must hold to reduce false positives:
       1. an imperative "do this" phrase is present,
       2. no '?' anywhere in the response,
       3. response is longer than 40 tokens (≈ rough word count).
    """
    answer_lower = answer.lower()
    imperative_hits = _hits(answer_lower, DIRECT_SOLUTION_IMPERATIVES)
    if not imperative_hits:
        return False, "", ""
    if "?" in answer:
        return False, "", ""
    if len(answer.split()) <= 40:
        return False, "", ""
    return True, f"imperative without question: {imperative_hits[0]}", "low"


def check_unsafe_end_chat(
    answer: str, conversation_history: list
) -> tuple[bool, str, str]:
    """Rules 14 + 15. '[END_CHAT]' is allowed only when at least one of:
       (a) at least one PRIOR assistant message contains a
           REFUSAL_KEYWORDS hit (a warning was already issued), OR
       (b) at least TWO PRIOR user messages hit ADVERSARIAL_TRIGGERS
           (repeated adversarial behavior — one is not enough), OR
       (c) the current answer contains a CONTEXT_MISMATCH_PHRASE
           (Rule 15 hardfail; one shot allowed).
    """
    if "[END_CHAT]" not in answer:
        return False, "", ""

    answer_lower = answer.lower()

    # (c) Rule 15 hardfail
    if any(p in answer_lower for p in CONTEXT_MISMATCH_PHRASES):
        return False, "", ""

    history = conversation_history or []

    # (a) prior assistant warning
    prior_warning = any(
        msg.get("role") == "assistant"
        and any(r in msg.get("content", "").lower() for r in REFUSAL_KEYWORDS)
        for msg in history
    )
    if prior_warning:
        return False, "", ""

    # (b) repeated adversarial user behavior
    adversarial_count = sum(
        1
        for msg in history
        if msg.get("role") == "user"
        and any(t in msg.get("content", "").lower() for t in ADVERSARIAL_TRIGGERS)
    )
    if adversarial_count >= 2:
        return False, "", ""

    return True, "[END_CHAT] without warning, repeated triggers, or hardfail", "medium"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _result(
    *,
    safe: bool,
    blocked: bool,
    violation_type: str,
    severity: str,
    action: str,
    evidence: str,
    final_answer: str,
) -> dict:
    return {
        "safe": safe,
        "blocked": blocked,
        "violation_type": violation_type,
        "severity": severity,
        "action": action,
        "evidence": evidence,
        "final_answer": final_answer,
    }


def apply_output_guardrails(
    answer: str,
    user_query: str,
    student_code: str,
    conversation_history: list,
) -> dict:
    """Run all detectors in priority order and return a structured
    result. First hit wins.

    Args:
        answer: the LLM's draft response (string).
        user_query: the most recent user message (string).
        student_code: the C++ source the student has open. Pass "" if
            none. Used as ground truth for the code-leakage check.
        conversation_history: list of prior turns, each shaped
            {"role": "user" | "assistant" | "system", "content": str}.
            Order is chronological (oldest first). Do NOT include the
            current draft `answer` in this list — pass only PRIOR
            turns. An empty list is fine for the first turn.

    Returns:
        dict with keys: safe, blocked, violation_type, severity,
        action ("pass" | "replace" | "log_only"), evidence,
        final_answer. See README / plan for details.
    """
    # 1. System prompt leakage
    violated, evidence, severity = check_system_prompt_leakage(answer)
    if violated:
        fb = get_fallback("system_prompt_leakage")
        return _result(
            safe=False, blocked=True,
            violation_type="system_prompt_leakage", severity=severity,
            action="replace", evidence=evidence, final_answer=fb,
        )

    # 2. Code leakage
    violated, evidence, severity = check_code_leakage(answer, student_code)
    if violated:
        fb = get_fallback("code_leakage")
        return _result(
            safe=False, blocked=True,
            violation_type="code_leakage", severity=severity,
            action="replace", evidence=evidence, final_answer=fb,
        )

    # 3. Off-topic leakage
    violated, evidence, severity = check_off_topic_leakage(answer, user_query)
    if violated:
        fb = get_fallback("off_topic")
        return _result(
            safe=False, blocked=True,
            violation_type="off_topic", severity=severity,
            action="replace", evidence=evidence, final_answer=fb,
        )

    # 4. Direct solution (log_only by default)
    violated, evidence, severity = check_direct_solution_leakage(answer)
    if violated:
        if STRICT_PEDAGOGY:
            fb = get_fallback("direct_solution")
            return _result(
                safe=False, blocked=True,
                violation_type="direct_solution", severity=severity,
                action="replace", evidence=evidence, final_answer=fb,
            )
        return _result(
            safe=False, blocked=False,
            violation_type="direct_solution", severity=severity,
            action="log_only", evidence=evidence, final_answer=answer,
        )

    # 5. Unsafe END_CHAT
    violated, evidence, severity = check_unsafe_end_chat(
        answer, conversation_history
    )
    if violated:
        fb = get_fallback("unsafe_end_chat")
        return _result(
            safe=False, blocked=True,
            violation_type="unsafe_end_chat", severity=severity,
            action="replace", evidence=evidence, final_answer=fb,
        )

    # No violation
    return _result(
        safe=True, blocked=False,
        violation_type="none", severity="",
        action="pass", evidence="", final_answer=answer,
    )
