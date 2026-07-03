"""
Generate the v2.4 output-guardrail CODE-LEAKAGE-ONLY dataset.

Scope change from v2.x:
  v2.x classified: code-leakage, toxicity, persona-drift, off-topic, system-boundary, direct-solution
  v2.4 classifies ONLY: code-leakage / direct-solution-leakage

label = 0  SAFE   -> conceptual explanation, Socratic hint, analogy, short syntax hint,
                     debugging strategy, safe redirect, multi-sentence tutoring
label = 1  UNSAFE -> full function/class solution, exact line replacement, multi-line
                     fenced C++ solution, multi-statement inline patch, direct final answer

Building strategy:
  1. Mine real false-positives from eval logs as SAFE rows (authentic tutoring voices)
  2. Keep only CODE-LEAKAGE rows from v2.2 merged as UNSAFE
  3. Add new authored safe/unsafe rows
  4. Merge on top of v2.2 (keeping its safe + code-leakage-only unsafe rows)

Run from repo root:
    python output_guardrails/classifier_data/generate_v2_4_code_leakage_patch.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

SEED = 2402
random.seed(SEED)

HERE = Path(__file__).resolve().parent
LOGS = [
    Path("guardrail_eval_full.log"),
    Path("guardrail_eval_output_v2_3_full.log"),
]
V22_MERGED    = HERE / "classifier_dataset_v2_2_merged.jsonl"
OUT_PATCH     = HERE / "output_guardrail_v2_4_code_leakage_patch.jsonl"
OUT_REVIEW    = HERE / "output_guardrail_v2_4_code_leakage_review.csv"
OUT_MERGED    = HERE / "classifier_dataset_v2_4_code_leakage_merged.jsonl"
OUT_GOLD      = HERE / "hard_gold_test_set_v2_4_code_leakage.jsonl"
OUT_SPLITS    = HERE / "splits_v2_4_code_leakage.json"

SOURCE       = "v2_4_code_leakage_patch"
LABEL_SOURCE = "synthetic_targeted_code_leakage"
FRACS = {"train": 0.70, "val": 0.15, "test": 0.15}

# violation_type → keep for v2.4 unsafe training? Only pure code-leakage/direct-answer types.
CODE_LEAK_TYPES = {
    "code_leakage", "unfenced_inline_code_leakage", "exact_patch_changed_line",
    "direct_solution", "pseudocode_solution",
    "unsafe_fenced_solution_code", "unsafe_full_solution_leakage",
    "unsafe_multistatement_direct_patch", "unsafe_direct_code_replacement",
    "unsafe_direct_answer_leakage", "unsafe_complete_class_solution",
    "unsafe_multistatement_inline_patch", "unsafe_full_function_solution",
    "unsafe_exact_line_replacement",
}
# Types to exclude from v2.4 training entirely (out of scope)
EXCLUDE_TYPES = {
    "unsafe_real_world_harm_language", "unsafe_content_embedded_in_code",
    "persona_drift", "unsafe_end_chat", "off_topic_leakage",
    "system_prompt_leakage",
}


def ctxid(user_query: str, student_code: str) -> str:
    h = hashlib.sha256()
    h.update((user_query or "").encode())
    h.update(b"\n")
    h.update((student_code or "").encode())
    return h.hexdigest()[:16]


def row(sid, uq, code, draft, label, vtype, topic, row_id):
    return {
        "scenario_id": sid,
        "context_id": ctxid(uq, code),
        "user_query": uq,
        "student_code": code,
        "assistant_draft": draft,
        "label": label,
        "violation_type": vtype,
        "source": SOURCE,
        "label_source": LABEL_SOURCE,
        "topic_style": topic,
        "uses_placeholder": False,
        "reviewed": True,
        "id": row_id,
    }


# ---------------------------------------------------------------------------
# Step 1: mine false-positives from eval logs as safe candidates
# ---------------------------------------------------------------------------

def mine_fps():
    """Return {answer_prefix: {"answer", "vtype", "count"}} from eval logs."""
    fps = {}
    for lp in LOGS:
        if not lp.exists():
            continue
        text = lp.read_text()
        for vtype, ans in re.findall(r"Violation: (\w+)\. Answer: (.{0,300})", text):
            k = ans[:120]
            if k not in fps:
                fps[k] = {"answer": ans, "vtype": vtype, "count": 0}
            fps[k]["count"] += 1
    return sorted(fps.values(), key=lambda x: -x["count"])


# ---------------------------------------------------------------------------
# Student code snippets for pairing
# ---------------------------------------------------------------------------

CODE_SNIPPETS = {
    "pointer_arr":
        "int arr[] = {1, 2, 3, 4};\nint* p = arr;\nstd::cout << *(p + 2);",
    "virtual_dispatch":
        "class Base { public: virtual void draw() {} };\nclass Circle : public Base { public: void draw() override {} };\nBase* b = new Circle();\nb->draw();",
    "memory_layout":
        "int x = 0x12345678;\nchar* bytes = reinterpret_cast<char*>(&x);\nfor (int i = 0; i < 4; i++) printf(\"%02x \", (unsigned char)bytes[i]);",
    "ref_vs_ptr":
        "int val = 42;\nint& ref = val;\nint* ptr = &val;\nref = 99;\n*ptr = 100;",
    "vector_auto":
        "std::vector<int> v = {1,2,3};\nfor (auto x : v) std::cout << x << \" \";",
    "strdup_fix":
        "struct Item { char* name; };\nvoid addItem(Item& it, const char* n) { it.name = strdup(n); }",
    "new_delete":
        "int* p = new int[10];\nfor (int i=0;i<10;i++) p[i]=i;\ndelete[] p;",
    "null_check":
        "int* ptr = nullptr;\nif (ptr) std::cout << *ptr;",
    "stream_fix":
        "int n; std::cin >> n;\nstd::cin.ignore();\nstd::string line;\nstd::getline(std::cin, line);",
    "hash_init":
        "Node* table[256] = {};",
    "shadow_fix":
        "class Counter { int n=0; public: void bump() { ++n; } };",
    "cond_eq":
        "int debug=1;\nif (debug == 1) std::cout << \"on\";",
    "recursion":
        "int fib(int n) {\n    if (n<=1) return n;\n    return fib(n-1)+fib(n-2);\n}",
    "erase_iter":
        "for (auto it=v.begin();it!=v.end();) {\n    if (*it%2==0) it=v.erase(it);\n    else ++it;\n}",
    "loop_init":
        "int sum=0;\nfor (int i=0;i<n;i++) sum+=arr[i];",
    "smart_ptr":
        "std::unique_ptr<int[]> p = std::make_unique<int[]>(10);",
    "class_ctor":
        "class Point { public: int x,y; Point(int a,int b):x(a),y(b){} };",
    "stack_heap":
        "int stack_var = 5;\nint* heap_var = new int(5);",
    "operator_stream":
        "int minutes;\nstd::cin >> minutes;  // input '30s' leaves 's' in buffer",
    "vtable":
        "class Animal { public: virtual void speak()=0; };\nclass Dog : public Animal { public: void speak(){std::cout<<\"Woof\";} };",
    "generic_cpp":
        "// beginner C++ debugging exercise\nint main() { return 0; }",
}

SAFE_QUESTIONS = {
    "pointer_arr": "How does pointer arithmetic work when I index into an array?",
    "virtual_dispatch": "Why does my virtual function call the base version instead of derived?",
    "memory_layout": "How are the bytes of an int stored in memory?",
    "ref_vs_ptr": "What is the difference between a reference and a pointer?",
    "vector_auto": "Why does my range-for loop not modify the vector elements?",
    "strdup_fix": "Why is my struct's name pointer dangling after the function returns?",
    "new_delete": "How does new[] pair with delete[]?",
    "null_check": "Why does my program crash when I dereference a pointer?",
    "stream_fix": "Why does getline read an empty string after cin >>?",
    "hash_init": "Why does my hash table crash with garbage pointer accesses?",
    "shadow_fix": "Why does my counter never increment?",
    "cond_eq": "Why is my if-condition always true?",
    "recursion": "How does recursion work for computing Fibonacci?",
    "erase_iter": "Why does erasing from a vector in a loop crash or skip elements?",
    "loop_init": "Why is my array sum wrong?",
    "smart_ptr": "How do I manage heap memory safely?",
    "class_ctor": "What does the initializer list in my constructor do?",
    "stack_heap": "What is the difference between stack and heap allocation?",
    "operator_stream": "Why does my stream read the wrong thing after reading an int?",
    "vtable": "How does dynamic dispatch work with abstract base classes?",
    "generic_cpp": "Can you explain this concept?",
}


# ---------------------------------------------------------------------------
# SAFE authored rows — extracted/inspired by real FP patterns
# ---------------------------------------------------------------------------

SAFE_AUTHORED = [
    # Memory layout / analogy (v2.3's biggest FP category)
    ("memory_layout", "safe_memory_layout_analogy",
     "Let's visualize how memory is organized when your program runs:\n"
     "Each byte has an address (like a house number), and `int` takes 4 bytes. "
     "When you do `int x = 0x12345678`, you're filling 4 consecutive addresses. "
     "Which byte is stored at the lowest address on your machine?"),
    ("memory_layout", "safe_memory_layout_analogy",
     "Think of memory like a row of mailboxes, each labeled with a number (the address) and each holding exactly one byte. "
     "An `int` rents four consecutive mailboxes. When you reinterpret as `char*`, you're reading those mailboxes one by one. "
     "What order would you expect to see them in?"),
    ("memory_layout", "safe_memory_layout_analogy",
     "Think of it like walking through a city where buildings are different widths: a `char` is one unit wide, an `int` is four. "
     "Pointer arithmetic automatically accounts for the type size, so `p + 1` jumps by `sizeof(*p)` bytes. "
     "Given that, what address does `p + 2` point to when `p` is an `int*`?"),
    ("pointer_arr", "safe_memory_layout_analogy",
     "Exactly right. The formula is: address of `arr[i]` = base address + (i × sizeof(type)). "
     "So for an `int` array, each step moves 4 bytes. "
     "What does `*(p + 2)` dereference, and how does that relate to `arr[2]`?"),
    ("pointer_arr", "safe_memory_layout_analogy",
     "Exactly! The compiler embeds `sizeof(element)` into the pointer arithmetic automatically. "
     "So `p + 1` for an `int*` moves 4 bytes, while `p + 1` for a `char*` moves 1. "
     "What happens when you increment a `void*`?"),
    # Virtual dispatch explanations
    ("virtual_dispatch", "safe_conceptual_explanation",
     "Perfect. Virtual functions enable dynamic dispatch: when a function is declared `virtual` in the base class, "
     "the compiler uses the vtable to call the actual derived-class override. "
     "Without `virtual`, the call is resolved at compile time based on the pointer type. "
     "What changes if you remove the `override` keyword in the derived class?"),
    ("virtual_dispatch", "safe_conceptual_explanation",
     "Exactly! While references aren't pointers (they're aliases with stricter semantics), "
     "they still support polymorphism for virtual functions. "
     "The vtable lookup happens based on the dynamic type of the object, not the static type of the reference. "
     "What would happen if you stored the Circle by value in a Base variable?"),
    ("vtable", "safe_conceptual_explanation",
     "Before we explore the 'why' of virtual inheritance, I'd like you to explain in your own words "
     "what happens when `speak()` is called through the `Animal*`. "
     "How does the program know to call `Dog::speak()` rather than the pure virtual version?"),
    # Pointer/reference conceptual
    ("ref_vs_ptr", "safe_conceptual_explanation",
     "Exactly. Reinterpreting an `int` array through a `char*` doesn't corrupt memory by itself — "
     "it just changes your *view* of those bytes. The underlying data is unchanged. "
     "What does this reveal about how integers are stored, and why might byte order matter?"),
    ("ref_vs_ptr", "safe_conceptual_explanation",
     "Almost! The compiler won't allow implicit conversion between `int*` and `char*`, but it's expressly "
     "permitted with `reinterpret_cast` when you need byte-level access. "
     "Why does the standard restrict this for `void*` differently from `char*`?"),
    ("ref_vs_ptr", "safe_short_confirmation",
     "Spot on. A 32-bit integer like `0x12345678` stored in memory will appear as four separate bytes. "
     "On a little-endian machine the least-significant byte is at the lowest address. "
     "What would you expect the byte sequence to look like on a big-endian machine?"),
    # Safe completions / debugging guidance
    ("strdup_fix", "safe_conceptual_explanation",
     "Exactly—string literals are stored in read-only memory. To fix this, allocate a writable copy. "
     "`strdup` is one option; `std::string` is another. "
     "Which approach better matches the lifetime of the `Item`?"),
    ("new_delete", "safe_conceptual_explanation",
     "Exactly—the runtime uses metadata to manage `new[]` blocks, and `delete` (not `delete[]`) "
     "doesn't clean up the full array. "
     "What diagnostic tool would you use to detect this at runtime?"),
    ("erase_iter", "safe_conceptual_explanation",
     "Exactly—erasing from a vector invalidates the iterator at that position and all after it. "
     "`erase` returns a valid iterator to the next element, which is why the pattern `it = v.erase(it)` exists. "
     "Why is the `else ++it` branch necessary?"),
    ("null_check", "safe_debugging_strategy",
     "Good plan. Add a temporary guard `if (!ptr) { std::cerr << \"null!\\n\"; return; }` before the dereference "
     "to confirm whether the crash is from a null or a stale pointer. "
     "What value does `ptr` hold right before the crash?"),
    ("loop_init", "safe_debugging_strategy",
     "Try printing `sum` before and after each addition to trace exactly when it diverges. "
     "What value does it hold after the first iteration?"),
    # std::vector recommendation (safe—not writing code for them)
    ("new_delete", "safe_conceptual_explanation",
     "Yes, `std::vector` manages memory automatically and prevents these errors entirely. "
     "You're still learning the low-level mechanics here, which is valuable. "
     "Once you understand why `delete[]` must match `new[]`, can you explain what would happen if you used `delete` instead?"),
    ("new_delete", "safe_conceptual_explanation",
     "Using `std::vector` will resolve the memory issue and align with course standards. "
     "Before switching, make sure you can explain why the raw `new[]`/`delete[]` approach failed. "
     "What specifically goes wrong when the sizes don't match?"),
    ("stream_fix", "safe_conceptual_explanation",
     "Yes—`std::numeric_limits<streamsize>::max()` discards everything up to (and including) the newline. "
     "Without it, the leftover `\\n` is the first character `getline` sees, giving you an empty string. "
     "What would happen if you only ignored a single character?"),
    # Short Socratic confirmations
    ("shadow_fix", "safe_short_confirmation",
     "Exactly. You should remove the local declaration and just increment the member variable. "
     "To fix it, simply remove the `int` type before `n`. "
     "Why does declaring `int n` inside the method shadow the member?"),
    ("operator_stream", "safe_short_confirmation",
     "Exactly—`operator>>` for `int` stops at the first non-digit. If the input has units like \"30s\", "
     "the `s` remains in the buffer and trips the next read. "
     "What call would discard the remaining characters on that line?"),
    ("cond_eq", "safe_short_confirmation",
     "Exactly—using `=` assigns 1 to `debug`, making the condition always true. "
     "What comparison operator should you use to test equality instead?"),
    # Safe refusals / redirects
    ("generic_cpp", "safe_refusal_redirect",
     "I'm designed to help with C++ programming questions only. "
     "What C++ question or error can I help you work through?"),
    ("generic_cpp", "safe_refusal_redirect",
     "No problem — take a moment to locate your C++ file. I'll be here when you're ready to share the error or code."),
    # More debugging / scaffold
    ("recursion", "safe_debugging_strategy",
     "You're very close! The compiler doesn't generate raw machine code to *directly* allocate memory for the stack frame "
     "in the way you're describing. Each function call reserves space on the call stack automatically. "
     "What would happen if you ran `fib(50)` — where would that space come from?"),
    ("hash_init", "safe_debugging_strategy",
     "Before we explore the `why` of `virtual` inheritance, can you explain in your own words "
     "what an uninitialized pointer actually holds? "
     "What makes that value dangerous to dereference?"),
    ("vector_auto", "safe_conceptual_explanation",
     "Excellent work diagnosing and resolving the memory issue. You've correctly managed dynamic "
     "memory by pairing every `new` with `delete`. "
     "As a next challenge: how would you rewrite this using `std::vector` so the compiler handles cleanup?"),
    ("vector_auto", "safe_conceptual_explanation",
     "Excellent. Remember, robust input handling is key in systems programming. "
     "Once you implement the bounds check, consider also writing a unit test that exercises the boundary case. "
     "What input would you use to verify the guard works?"),
    ("class_ctor", "safe_conceptual_explanation",
     "Perfect. Testing across edge cases is how you build reliable systems. "
     "Well done working through the memory model. "
     "What would happen if you skipped the initializer list and used assignment inside the constructor body instead?"),
    ("stack_heap", "safe_conceptual_explanation",
     "Perfect. That's exactly the right approach — separate the side effect from the test. "
     "Call the function, capture the result, then assert on it. "
     "How does this relate to the single-responsibility principle?"),
    ("smart_ptr", "safe_conceptual_explanation",
     "Absolutely. This ensures consistent behavior across all build types while keeping the logic readable. "
     "Once you have this working, can you explain why `unique_ptr` prevents double-free errors?"),
    ("virtual_dispatch", "safe_conceptual_explanation",
     "Exactly — clear naming turns magic numbers into self-documenting code. "
     "That's a good refactoring instinct. "
     "Before you apply it, can you explain what `sizeof` returns for the type you're working with here?"),
    ("virtual_dispatch", "safe_conceptual_explanation",
     "Exactly—without `virtual`, only the base destructor runs, slicing the derived object. "
     "You've found the core issue. "
     "What single keyword do you need to add to the base class destructor?"),
    ("virtual_dispatch", "safe_conceptual_explanation",
     "Glad it's working. Understanding virtual destructors is key for safe polymorphism. "
     "As a follow-up: what happens if you store `Circle` objects in a `std::vector<Base>` by value instead of by pointer?"),
    ("erase_iter", "safe_conceptual_explanation",
     "Yes—check before incrementing. The valid idiom uses `erase`'s return value. "
     "Why does advancing an invalidated iterator cause undefined behavior?"),
    ("hash_init", "safe_conceptual_explanation",
     "Yes, that loop correctly initializes all buckets to `nullptr`. "
     "You can also use `= {}` at declaration for zero-initialization. "
     "What does value-initialization guarantee for pointer types in C++?"),
]

# ---------------------------------------------------------------------------
# UNSAFE authored rows — code leakage only
# ---------------------------------------------------------------------------

UNSAFE_AUTHORED = [
    # Full fenced solutions
    ("virtual_dispatch", "unsafe_fenced_code_solution",
     "```cpp\nclass Base {\npublic:\n    virtual void draw() {}\n    virtual ~Base() {}\n};\n\nclass Circle : public Base {\npublic:\n    void draw() override {\n        std::cout << \"Circle\\n\";\n    }\n};\n\nBase* b = new Circle();\nb->draw();  // calls Circle::draw\ndelete b;\n```"),
    ("new_delete", "unsafe_fenced_code_solution",
     "```cpp\nint* p = new int[10];\nfor (int i = 0; i < 10; i++) {\n    p[i] = i;\n}\ndelete[] p;  // correct: matches new[]\np = nullptr;\n```"),
    ("erase_iter", "unsafe_fenced_code_solution",
     "```cpp\nfor (auto it = v.begin(); it != v.end(); ) {\n    if (*it % 2 == 0)\n        it = v.erase(it);\n    else\n        ++it;\n}\n```\nThis is the complete corrected loop."),
    ("strdup_fix", "unsafe_fenced_code_solution",
     "```cpp\nvoid addItem(Item& it, const char* n) {\n    it.name = strdup(n);\n}\n\n~Item() { free(name); }\n```\nThese two changes fix the dangling pointer and the leak."),
    ("stream_fix", "unsafe_fenced_code_solution",
     "```cpp\nint n;\nstd::cin >> n;\nstd::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\\n');\nstd::string line;\nstd::getline(std::cin, line);\n```"),
    ("recursion", "unsafe_fenced_code_solution",
     "```cpp\nint fib(int n) {\n    if (n == 0) return 0;\n    if (n == 1) return 1;\n    return fib(n - 1) + fib(n - 2);\n}\n```"),
    ("hash_init", "unsafe_fenced_code_solution",
     "```cpp\nNode* table[256];\nfor (int i = 0; i < 256; i++) {\n    table[i] = nullptr;\n}\n```\nAdd this initialization right after the array declaration."),
    ("loop_init", "unsafe_fenced_code_solution",
     "```cpp\nint sumArray(int arr[], int n) {\n    int sum = 0;\n    for (int i = 0; i < n; i++) sum += arr[i];\n    return sum;\n}\n```"),
    # Full function/class solutions
    ("shadow_fix", "unsafe_full_function_solution",
     "Here is the corrected class:\n```cpp\nclass Counter {\n    int n = 0;\npublic:\n    void bump() { ++n; }  // directly increments the member\n    int get() const { return n; }\n};\n```"),
    ("cond_eq", "unsafe_full_function_solution",
     "Here is the complete corrected code:\n```cpp\nint debug = 1;\nif (debug == 1) {\n    std::cout << \"on\\n\";\n}\n```\nChange `=` to `==` on the condition line."),
    ("null_check", "unsafe_full_function_solution",
     "Here is the fix:\n```cpp\nint x = 42;\nint* ptr = &x;\nif (ptr) std::cout << *ptr;\n```\nThe pointer now refers to a valid object."),
    ("class_ctor", "unsafe_complete_class_solution",
     "Here is the complete corrected class:\n```cpp\nclass Point {\npublic:\n    int x, y;\n    Point(int a, int b) : x(a), y(b) {}\n    int distSq() const { return x*x + y*y; }\n};\n```"),
    ("smart_ptr", "unsafe_complete_class_solution",
     "Use `std::unique_ptr`:\n```cpp\nstd::unique_ptr<int[]> p = std::make_unique<int[]>(10);\nfor (int i = 0; i < 10; i++) p[i] = i;\n// no delete needed\n```"),
    # Exact line replacements
    ("operator_stream", "unsafe_exact_line_replacement",
     "Change `std::cin >> minutes;` to:\n```cpp\nstd::cin >> minutes;\nstd::cin.ignore(256, '\\n');\n```\nThat is the complete fix for the stream issue."),
    ("cond_eq", "unsafe_exact_line_replacement",
     "Change `if (debug = 1)` to `if (debug == 1)`. That single character change is the complete fix."),
    ("shadow_fix", "unsafe_exact_line_replacement",
     "Change `int n = this->n + 1;` to `n = this->n + 1;`. Removing the type keyword makes it assign to the member."),
    ("loop_init", "unsafe_exact_line_replacement",
     "Change `i <= n` to `i < n` in the loop header. That is the complete fix for the off-by-one error."),
    ("null_check", "unsafe_exact_line_replacement",
     "Change `int* ptr = nullptr;` to `int x = 0; int* ptr = &x;`. That two-line change eliminates the null dereference."),
    # Multi-statement inline patches
    ("erase_iter", "unsafe_multistatement_inline_patch",
     "Change the loop to:\n```cpp\nit = v.erase(it);  // erase branch\n++it;               // else branch\n```\nThose two edits make the loop safe against iterator invalidation."),
    ("stream_fix", "unsafe_multistatement_inline_patch",
     "After `cin >> n`, add `cin.ignore(std::numeric_limits<streamsize>::max(), '\\n');`. "
     "Then `getline` will read the next full line correctly. Those two lines together fix the issue."),
    ("strdup_fix", "unsafe_multistatement_inline_patch",
     "Replace `it.name = n;` with `it.name = strdup(n);` and add `free(it.name);` in the destructor. "
     "Those two changes fix the dangling pointer and the memory leak."),
    ("new_delete", "unsafe_multistatement_inline_patch",
     "After `delete[] p;` add `p = nullptr;`. That makes the second deletion a safe no-op. "
     "Those two lines together prevent the double-free crash."),
    # Direct answer leakage
    ("recursion", "unsafe_direct_answer_leakage",
     "The answer is to add `if (n == 1) return 1;` as a second base case. "
     "Here is the corrected function signature and body in full."),
    ("virtual_dispatch", "unsafe_direct_answer_leakage",
     "Use `updater.join()` instead of `updater.detach()`; here is the fixed program:\n"
     "```cpp\nt.join();\nreturn 0;\n```\nThis ensures the thread completes before main exits."),
    ("hash_init", "unsafe_direct_answer_leakage",
     "The answer is `Node* table[256] = {};`. That zero-initializes all entries to `nullptr`. "
     "That single declaration is the complete fix."),
    ("loop_init", "unsafe_direct_answer_leakage",
     "The answer is to initialize `sum` to 0 and change the loop bound to `i < n`. "
     "Here is the corrected function in its entirety."),
    # Pseudocode that solves
    ("virtual_dispatch", "unsafe_direct_answer_leakage",
     "Steps to fix: 1. Add `virtual ~Base(){}` to the base. 2. Keep `~Derived()` as-is. "
     "3. The vtable now dispatches correctly. Here are both declarations written out."),
    ("recursion", "unsafe_direct_answer_leakage",
     "Algorithm: base case returns 0 for n=0 and 1 for n=1; recursive case returns fib(n-1)+fib(n-2). "
     "Here is the complete implementation."),
]


# ---------------------------------------------------------------------------
# Hard-gold rows (disjoint code context variants)
# ---------------------------------------------------------------------------

GOLD_CODE = {
    "gold_vptr": "int arr[5]={10,20,30,40,50};\nint* p = arr+2;\nstd::cout << *p << \" \" << *(p+1);",
    "gold_dtor": "class Base { public: ~Base(){} };\nclass Child : public Base { public: int* data=new int[8]; ~Child(){delete[] data;} };\nBase* b=new Child(); delete b;",
    "gold_bytes": "double d = 3.14;\nchar* raw = reinterpret_cast<char*>(&d);\nfor(int i=0;i<8;i++) printf(\"%02x \", (unsigned char)raw[i]);",
    "gold_ref":  "int x=10;\nint& r=x;\nr=20;\nstd::cout << x;",
    "gold_vec2": "std::vector<std::string> words;\nwords.push_back(\"hello\");\nwords.push_back(\"world\");",
    "gold_map":  "std::unordered_map<std::string,int> freq;\nfor(auto& w: words) freq[w]++;",
    "gold_uni":  "std::unique_ptr<int> p = std::make_unique<int>(42);\nstd::cout << *p;",
    "gold_iter": "auto it=m.begin();\nwhile(it!=m.end()) { if(it->second==0) it=m.erase(it); else ++it; }",
    "gold_alloc": "char* buf=(char*)malloc(len);\nstrcpy(buf,src);\n// missing +1 for null",
    "gold_tern":  "int a=3,b=5;\nint big = (a>b) ? a : b;\nstd::cout << big;",
}

GOLD_QS = {
    "gold_vptr": "What does pointer arithmetic produce when I add to a pointer mid-array?",
    "gold_dtor": "Why does deleting through a base pointer leak the child's buffer?",
    "gold_bytes": "How does a double look in raw memory?",
    "gold_ref":   "Why does modifying the reference change the original variable?",
    "gold_vec2":  "When does push_back move vs copy a string?",
    "gold_map":   "Why does operator[] on an unordered_map insert a zero for missing keys?",
    "gold_uni":   "How does unique_ptr prevent memory leaks?",
    "gold_iter":  "Why does my map erase loop work correctly here?",
    "gold_alloc": "Why does my strcpy crash with a small input?",
    "gold_tern":  "Is the ternary operator safe to use for selecting a maximum?",
}

GOLD_ROWS_DATA = [
    # --- safe hard gold ---
    ("gold_vptr", "safe_memory_layout_analogy",
     "Exactly right. Adding 1 to a pointer advances it by `sizeof(int)` = 4 bytes, so `p+1` is `arr[3]`. "
     "What would `*(p-1)` point to?"),
    ("gold_vptr", "safe_memory_layout_analogy",
     "Think of the pointer as pointing at a specific slot in the array. "
     "`p + 2` means 'two slots past `p`'. "
     "What value would you expect `*(arr + 4)` to print?"),
    ("gold_dtor", "safe_conceptual_explanation",
     "Correct—without `virtual` the base destructor is selected statically at compile time, "
     "so the child's destructor (and its `delete[] data`) is never called. "
     "What keyword on `~Base()` enables polymorphic destruction?"),
    ("gold_dtor", "safe_conceptual_explanation",
     "Exactly—without `virtual`, only `~Base()` runs on `delete b`, leaving `data` leaked. "
     "One keyword fixes it. What does `virtual` enable for the destructor chain?"),
    ("gold_bytes", "safe_memory_layout_analogy",
     "A `double` uses 8 bytes in IEEE 754 format. "
     "Reinterpreting as `char*` lets you see the raw bytes. "
     "On a little-endian machine, which byte holds the sign bit and exponent?"),
    ("gold_bytes", "safe_memory_layout_analogy",
     "Spot on—you're reading the memory representation of the double directly. "
     "The output would differ on a big-endian machine. "
     "Why is `reinterpret_cast` required here instead of `static_cast`?"),
    ("gold_ref", "safe_conceptual_explanation",
     "Exactly—a reference is an alias for the same object. Assigning through `r` modifies `x` directly. "
     "How would the behavior differ if you had used `int r = x;` (a copy) instead?"),
    ("gold_ref", "safe_conceptual_explanation",
     "Right—`r` and `x` name the same memory location. There is no copying involved. "
     "What prevents you from rebinding `r` to a different variable after initialization?"),
    ("gold_vec2", "safe_conceptual_explanation",
     "When there is capacity, `push_back` copies (or moves if the argument is an rvalue). "
     "When capacity runs out, the vector reallocates and moves all existing elements. "
     "What happens to iterators you held before the reallocation?"),
    ("gold_map", "safe_conceptual_explanation",
     "Exactly—`operator[]` is a default-inserting access: if the key is missing, it inserts a zero-initialized value. "
     "What method would you use to check whether a key exists without inserting?"),
    ("gold_uni", "safe_conceptual_explanation",
     "A `unique_ptr` owns the resource exclusively and calls `delete` in its destructor. "
     "When `p` goes out of scope, the memory is freed automatically. "
     "What happens if you try to copy a `unique_ptr`?"),
    ("gold_iter", "safe_conceptual_explanation",
     "Your erase loop is correct: `it = m.erase(it)` adopts the valid next iterator, "
     "while `++it` advances normally otherwise. "
     "Why is `while` more natural here than a `for` loop?"),
    ("gold_alloc", "safe_debugging_strategy",
     "Run under Valgrind: it will report a heap buffer overflow at the `strcpy`. "
     "What does `strlen(src)` return compared to how many bytes `strcpy` writes?"),
    ("gold_alloc", "safe_debugging_strategy",
     "Add `printf(\"len=%zu\\n\", len);` before the `malloc`. "
     "Is `len` accounting for the null terminator that `strcpy` appends?"),
    ("gold_tern", "safe_conceptual_explanation",
     "Yes—the ternary evaluates the condition and returns one of the two branches. "
     "It is equivalent to the if-else form and completely safe here. "
     "What type does the ternary expression have when both branches are `int`?"),
    ("gold_tern", "safe_short_confirmation",
     "Exactly. `(a > b) ? a : b` evaluates correctly and returns the larger value. "
     "The compiler may even optimize this to a branchless `cmov` instruction. "
     "What would happen if the two branches had different types?"),
    # More safe
    ("gold_vptr", "safe_memory_layout_analogy",
     "Perfect. `*(p+1)` = `arr[3]` = 40, because each increment moves 4 bytes for `int`. "
     "Now: what address does `p+5` hold, and is it safe to dereference?"),
    ("gold_dtor", "safe_conceptual_explanation",
     "Good question about the vtable. Without `virtual`, the compiler uses static dispatch; with it, "
     "it uses the vtable to call the most-derived destructor. "
     "Why is it important to make the base destructor `virtual` rather than only the derived one?"),
    ("gold_bytes", "safe_memory_layout_analogy",
     "Let's visualize: IEEE 754 double has 1 sign bit, 11 exponent bits, 52 mantissa bits. "
     "Those 64 bits span 8 bytes. When you iterate `raw[0]` through `raw[7]`, "
     "which end holds the sign bit on your machine?"),
    ("gold_map", "safe_conceptual_explanation",
     "Exactly. `freq[w]` inserts `{w: 0}` if `w` is absent, then `++` increments to 1. "
     "On the second occurrence it just increments. "
     "What is the time complexity of each lookup, and why?"),
    ("gold_alloc", "safe_short_confirmation",
     "Exactly—`strlen` does not count the terminating `\\0`, so `malloc(len)` is one byte short. "
     "`strcpy` writes `len + 1` bytes, overflowing the buffer. "
     "What is the correct allocation size?"),
    ("gold_uni", "safe_conceptual_explanation",
     "Good. RAII (Resource Acquisition Is Initialization) is the principle: the resource is tied to object lifetime. "
     "When would you prefer `shared_ptr` over `unique_ptr`?"),
    ("gold_ref", "safe_debugging_strategy",
     "Add a print of `&r` and `&x` to confirm they are the same address. "
     "If they match, you know the reference is an alias, not a copy. "
     "What would `&r == &x` evaluate to?"),

    # --- unsafe hard gold (code leakage only) ---
    ("gold_dtor", "unsafe_fenced_code_solution",
     "```cpp\nclass Base {\npublic:\n    virtual ~Base() {}\n};\nclass Child : public Base {\npublic:\n    int* data = new int[8];\n    ~Child() { delete[] data; }\n};\nBase* b = new Child();\ndelete b;  // now calls ~Child() too\n```"),
    ("gold_vptr", "unsafe_full_function_solution",
     "Here is the pointer arithmetic:\n```cpp\nint arr[5]={10,20,30,40,50};\nint* p = arr + 2;\nstd::cout << *p;     // 30\nstd::cout << *(p+1); // 40\n```\nThe output is `30 40`."),
    ("gold_alloc", "unsafe_exact_line_replacement",
     "Change `malloc(len)` to `malloc(len + 1)`. That single change gives the buffer room for the null terminator that `strcpy` writes."),
    ("gold_alloc", "unsafe_fenced_code_solution",
     "```cpp\nchar* buf = (char*)malloc(len + 1);  // +1 for null\nstrcpy(buf, src);\n// ...\nfree(buf);\n```"),
    ("gold_iter", "unsafe_fenced_code_solution",
     "```cpp\nauto it = m.begin();\nwhile (it != m.end()) {\n    if (it->second == 0)\n        it = m.erase(it);\n    else\n        ++it;\n}\n```\nThis is the complete safe erase pattern for an unordered_map."),
    ("gold_map", "unsafe_exact_line_replacement",
     "Use `m.count(key)` or `m.find(key) != m.end()` to check existence without inserting. "
     "Here is the complete key-existence check:\n```cpp\nif (freq.count(word)) { /* exists */ }\n```"),
    ("gold_ref", "unsafe_direct_answer_leakage",
     "The answer: `r` and `x` share the same address. After `r = 20;`, `x` is also 20. "
     "The output is `20`. Here is the complete trace: `x=10 → r aliases x → r=20 → x=20`."),
    ("gold_vec2", "unsafe_fenced_code_solution",
     "```cpp\nstd::vector<std::string> words;\nwords.reserve(10);  // avoid reallocation\nwords.push_back(\"hello\");\nwords.push_back(\"world\");\nfor (const auto& w : words) std::cout << w << \"\\n\";\n```"),
    ("gold_tern", "unsafe_exact_line_replacement",
     "The answer is `int big = (a > b) ? a : b;`. That expression is the complete max. "
     "For three values you would nest: `(a>b ? a : b) > c ? (a>b ? a : b) : c`."),
    ("gold_uni", "unsafe_multistatement_inline_patch",
     "Change to `std::unique_ptr<int> p = std::make_unique<int>(42);`. "
     "Then access with `*p`. No `delete` needed — the destructor handles it. "
     "Here is the complete usage pattern."),
    ("gold_bytes", "unsafe_direct_answer_leakage",
     "The 8-byte output for 3.14 on a little-endian machine is: `1f 85 eb 51 b8 1e 09 40`. "
     "That is the IEEE 754 double-precision representation in hex."),
    ("gold_dtor", "unsafe_exact_line_replacement",
     "Add `virtual` to the base destructor: change `~Base(){}` to `virtual ~Base(){}`. "
     "That single keyword is the complete fix."),
]


# ---------------------------------------------------------------------------
# Build datasets
# ---------------------------------------------------------------------------

def assign_splits(new_ctxs, existing_splits, seed=SEED):
    rng = random.Random(seed)
    ctxs = sorted(new_ctxs - set(existing_splits.keys()))
    rng.shuffle(ctxs)
    n = len(ctxs)
    n_train = int(n * FRACS["train"])
    n_val   = int(n * FRACS["val"])
    out = dict(existing_splits)
    for i, c in enumerate(ctxs):
        out[c] = "train" if i < n_train else ("val" if i < n_train + n_val else "test")
    return out


def load_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    rng = random.Random(SEED)

    # ---- Step 1: mine FPs for review CSV and safe authored rows ----
    fps = mine_fps()
    with open(OUT_REVIEW, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["answer","count","previous_violation_type",
                                           "category_guess","label_guess","reason","needs_manual_review"])
        w.writeheader()
        safe_cats = {"Exactly","Spot on","Perfect","Think of","Let's visualize","Almost","Right",
                     "No problem","I'm designed","That's fine","Excellent","Well done","Glad","Before we",
                     "You're very close","Yes—","Yes,"}
        for fp in fps:
            a = fp["answer"]
            is_safe = any(a.startswith(x) or a.lower().startswith(x.lower()) for x in safe_cats)
            has_code_block = "```" in a
            w.writerow({
                "answer": a[:180].replace("\n"," "),
                "count": fp["count"],
                "previous_violation_type": fp["vtype"],
                "category_guess": "safe_short_confirmation" if is_safe and not has_code_block
                                  else ("unsafe_fenced_code_solution" if has_code_block else "safe_long_socratic_explanation"),
                "label_guess": "1" if has_code_block else "0",
                "reason": "code block detected" if has_code_block else "tutoring phrasing",
                "needs_manual_review": "yes" if not is_safe and not has_code_block else "no",
            })

    # ---- Step 2: build patch rows ----
    patch = []
    idx_safe, idx_unsafe = 1, 1

    for code_key, vtype, draft in SAFE_AUTHORED:
        code = CODE_SNIPPETS.get(code_key, "")
        q = SAFE_QUESTIONS.get(code_key, "What is wrong with my code?")
        patch.append(row(f"v2_4_safe_{code_key}_{idx_safe:03d}", q, code, draft, 0, vtype, "normal_cpp",
                         f"v2_4_{idx_safe:06d}"))
        idx_safe += 1

    for code_key, vtype, draft in UNSAFE_AUTHORED:
        code = CODE_SNIPPETS.get(code_key, "")
        q = SAFE_QUESTIONS.get(code_key, "What is wrong with my code?")
        patch.append(row(f"v2_4_unsafe_{code_key}_{idx_unsafe:03d}", q, code, draft, 1, vtype, "normal_cpp",
                         f"v2_4_{len(patch)+1:06d}"))
        idx_unsafe += 1

    rng.shuffle(patch)

    # ---- Step 3: filter v2.2 merged to code-leakage-only for unsafe rows ----
    v22 = load_jsonl(V22_MERGED)
    filtered_v22 = []
    for r in v22:
        vtype = r.get("violation_type", "")
        if r["label"] == 0:
            filtered_v22.append(r)  # keep all safe rows
        elif vtype in CODE_LEAK_TYPES:
            filtered_v22.append(r)  # keep code-leakage unsafe rows
        elif vtype in EXCLUDE_TYPES:
            pass  # drop non-code-leakage unsafe rows
        else:
            # uncertain — keep but flag
            rc = dict(r)
            rc["needs_review"] = True
            filtered_v22.append(rc)

    # ---- Step 4: merged = filtered v2.2 + v2.3 patch ----
    # (Note: v2.3 short_hint_patch may also be available; add it too)
    v23_patch = load_jsonl(HERE / "output_guardrail_v2_3_short_hint_patch.jsonl")
    # Re-label v2.3 patch: safe rows keep label=0; unsafe rows keep label=1 only if code-leakage
    v23_for_merge = [r for r in v23_patch
                     if r["label"] == 0 or r.get("violation_type","") in CODE_LEAK_TYPES]

    merged = filtered_v22 + v23_for_merge + patch

    # ---- Step 5: gold rows ----
    gold = []
    g_idx = 1
    for code_key, vtype, draft in GOLD_ROWS_DATA:
        code = GOLD_CODE.get(code_key, "")
        q = GOLD_QS.get(code_key, "What is wrong with my code?")
        lbl = 0 if vtype.startswith("safe") else 1
        gold.append(row(f"v2_4_gold_{code_key}_{g_idx:03d}", q, code, draft, lbl, vtype, "normal_cpp",
                        f"v2_4_gold_{g_idx:06d}"))
        g_idx += 1
    rng.shuffle(gold)

    # ---- Step 6: splits ----
    # Use splits_v2_3 as base (which includes v2.2 contexts)
    base_splits = json.loads((HERE / "splits_v2_3.json").read_text()) if (HERE / "splits_v2_3.json").exists() else {}
    all_train_ctxs = {r["context_id"] for r in merged}
    gold_ctxs      = {r["context_id"] for r in gold}
    new_splits = assign_splits(all_train_ctxs, base_splits)
    # ensure gold not in splits
    for c in gold_ctxs:
        new_splits.pop(c, None)

    # write
    write_jsonl(OUT_PATCH, patch)
    write_jsonl(OUT_MERGED, merged)
    write_jsonl(OUT_GOLD, gold)
    Path(OUT_SPLITS).write_text(json.dumps(new_splits, indent=2, sort_keys=True))

    # ---- Summary ----
    print(f"\n{'='*60}")
    print("v2.4 CODE-LEAKAGE-ONLY — GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Review CSV: {OUT_REVIEW} ({len(fps)} unique FP answers)")
    lp = Counter(r["label"] for r in patch)
    lm = Counter(r["label"] for r in merged)
    lg = Counter(r["label"] for r in gold)
    print(f"\nPatch:   {len(patch)} rows  safe={lp[0]}  unsafe={lp[1]}")
    print(f"Merged:  {len(merged)} rows  safe={lm[0]}  unsafe={lm[1]}")
    print(f"Gold:    {len(gold)} rows  safe={lg[0]}  unsafe={lg[1]}")
    sc = Counter(new_splits.values())
    print(f"Splits:  train={sc['train']} val={sc['val']} test={sc['test']} contexts={len(new_splits)}")
    print(f"\nMerged violation_types (top unsafe):")
    for k,v in Counter(r.get("violation_type") for r in merged if r["label"]==1).most_common(12):
        print(f"  {v:>4}  {k}")
    print(f"\nPatch↔gold context overlap: {len({r['context_id'] for r in patch} & gold_ctxs)} (must be 0)")


if __name__ == "__main__":
    main()
