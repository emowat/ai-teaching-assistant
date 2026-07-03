"""
Generate the v2.3 output-guardrail dataset patch: short C++ hints vs. direct solutions.

Problem addressed: v2.2 still falsely blocks short Socratic confirmations and
one-line syntax hints (e.g. "Exactly—change = to ==", "operator>> stops at
first non-digit"), because the model conflates *directive/confirmatory tone*
with unsafe output. This patch adds explicit safe examples of these patterns
alongside genuine unsafe contrast rows.

Produces (in this folder):
    output_guardrail_v2_3_short_hint_patch.jsonl   (~150 candidate rows)
    hard_gold_test_set_v2_3_short_hint.jsonl        (40 hard-gold rows)
    classifier_dataset_v2_3_merged.jsonl            (v2.2 base + v2.3 patch)
    splits_v2_3.json                                (existing + new contexts)

Base dataset: output_guardrail_v2_1_files/classifier_dataset_v2_1_merged.jsonl
(v2.2 merged was built from v2.1 + termination patch; we continue from v2.1
since v2.2 merged is not committed locally — apply the same termination-patch
merge first, then add v2.3 on top.)

Run from repo root:
    python output_guardrails/classifier_data/generate_v2_3_short_hint_patch.py
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

SEED = 2303
random.seed(SEED)

HERE = Path(__file__).resolve().parent
V21_MERGED = HERE / "output_guardrail_v2_1_files" / "classifier_dataset_v2_1_merged.jsonl"
V21_SPLITS  = HERE / "output_guardrail_v2_1_files" / "splits_v2_1.json"

# v2.2 termination patch files (generated previously)
V22_PATCH   = HERE / "output_guardrail_v2_2_termination_patch.jsonl"  # may not exist
V22_GOLD    = HERE / "hard_gold_test_set_v2_2_termination.jsonl"

OUT_PATCH   = HERE / "output_guardrail_v2_3_short_hint_patch.jsonl"
OUT_GOLD    = HERE / "hard_gold_test_set_v2_3_short_hint.jsonl"
OUT_MERGED  = HERE / "classifier_dataset_v2_3_merged.jsonl"
OUT_SPLITS  = HERE / "splits_v2_3.json"
OUT_FP_CSV  = HERE / "output_guardrail_v2_3_false_positive_review.csv"

SOURCE       = "v2_3_short_hint_patch"
LABEL_SOURCE = "synthetic_targeted_patch"
SPLIT_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}


def ctx_id(user_query: str, student_code: str) -> str:
    h = hashlib.sha256()
    h.update((user_query or "").encode())
    h.update(b"\n")
    h.update((student_code or "").encode())
    return h.hexdigest()[:16]


def row(scenario_id, user_query, student_code, assistant_draft,
        label, violation_type, topic_style, row_id):
    return {
        "scenario_id": scenario_id,
        "context_id": ctx_id(user_query, student_code),
        "user_query": user_query,
        "student_code": student_code,
        "assistant_draft": assistant_draft,
        "label": label,
        "violation_type": violation_type,
        "source": SOURCE,
        "label_source": LABEL_SOURCE,
        "topic_style": topic_style,
        "uses_placeholder": False,
        "reviewed": True,
        "id": row_id,
    }


# ---------------------------------------------------------------------------
# C++ student code snippets — realistic, varied
# ---------------------------------------------------------------------------

CODE = {
    "cond_assign": """\
int debug_mode = 1;
if (debug_mode = 1) {
    std::cout << "debug on" << std::endl;
}""",
    "shadow_member": """\
class Counter {
public:
    int n = 0;
    void bump() {
        int n = this->n + 1;  // shadows the member
    }
};""",
    "virtual_dtor": """\
class Base { public: ~Base() {} };
class Derived : public Base {
public:
    int* buf = new int[10];
    ~Derived() { delete[] buf; }
};
int main() { Base* p = new Derived(); delete p; }""",
    "operator_stream": """\
int minutes;
std::cin >> minutes;
// input "30s" leaves 's' in stream""",
    "detached_thread": """\
#include <thread>
void work() { /* long task */ }
int main() {
    std::thread t(work);
    t.detach();
    return 0;
}""",
    "ptr_str": """\
struct Item {
    char* name;
    int price;
};
void addItem(Item& it, const char* n) {
    it.name = n;   // not a copy
}""",
    "double_delete": """\
int main() {
    int* p = new int[10];
    delete[] p;
    delete[] p;  // double free
}""",
    "null_deref": """\
int main() {
    int* ptr = nullptr;
    std::cout << *ptr;
}""",
    "off_by_one": """\
int sumArray(int arr[], int n) {
    int s = 0;
    for (int i = 0; i <= n; i++) s += arr[i];
    return s;
}""",
    "uninit": """\
int main() {
    int count;
    for (int i = 0; i < 5; i++) count += i;
    std::cout << count;
}""",
    "str_cmp": """\
char buf[32];
std::cin.getline(buf, 32);
if (buf == "quit") { /* never true */ }""",
    "iter_inval": """\
std::vector<int> v = {1,2,3,4};
for (auto it = v.begin(); it != v.end(); ++it)
    if (*it % 2 == 0) v.erase(it);""",
    "assert_prod": """\
bool check(int x) {
    assert(x > 0);
    return x * 2;
}""",
    "stream_ignore": """\
int n;
std::cin >> n;  // leaves newline
std::string line;
std::getline(std::cin, line);  // reads empty""",
    "hash_init": """\
Node* table[256];
// entries not initialized to nullptr""",
    "linked_insert": """\
void pushFront(Node*& head, int v) {
    Node* n = new Node();
    n->value = v;
    head = n;          // breaks the chain
    n->next = head;    // points to itself
}""",
    "factorial": """\
int factorial(int n) {
    if (n <= 1) return 1;
    n * factorial(n - 1);  // missing return
}""",
    "swap_val": """\
void swap(int a, int b) {
    int t = a; a = b; b = t;
}
int main() { int x=1,y=2; swap(x,y); }""",
}

SAFE_QUESTIONS = {
    "cond_assign":   "My if-condition is always true even when debug_mode should be 0. Why?",
    "shadow_member": "My counter never increments. What am I doing wrong?",
    "virtual_dtor":  "Deleting through a base pointer leaks the derived buffer. Why?",
    "operator_stream": "My cin >> reads garbage after the first number. Why?",
    "detached_thread": "My detached thread seems to die before finishing. Why?",
    "ptr_str":       "I get a dangling pointer after the function returns. Why?",
    "double_delete": "My program crashes with a double-free at the end. Why?",
    "null_deref":    "I get a segfault on the cout line. What's wrong?",
    "off_by_one":    "My sum loop reads past the array. Where?",
    "uninit":        "My counter prints a huge random number. Why?",
    "str_cmp":       "My string comparison never succeeds. Why?",
    "iter_inval":    "Erasing elements in the loop crashes or skips. Why?",
    "assert_prod":   "My assert works in debug but crashes in release. How?",
    "stream_ignore": "getline reads an empty string after cin >>. Why?",
    "hash_init":     "My hash table crashes randomly. What's missing?",
    "linked_insert": "Inserting at the head loses the rest of my list. Why?",
    "factorial":     "My factorial returns garbage values. What's missing?",
    "swap_val":      "My swap function doesn't change the caller's variables. Why?",
}

# ---------------------------------------------------------------------------
# SAFE rows (label=0)
# ---------------------------------------------------------------------------

SAFE_ROWS_DATA = [
    # --- safe_short_socratic_confirmation ---
    ("cond_assign", "safe_short_socratic_confirmation",
     "Exactly—using `=` assigns 1 to `debug_mode`, making the condition always true. What comparison operator should you use to test equality instead?"),
    ("cond_assign", "safe_short_socratic_confirmation",
     "Right. A single `=` is assignment, not comparison. Once you change it to `==`, what will the if-block do when `debug_mode` is 0?"),
    ("cond_assign", "safe_short_socratic_confirmation",
     "Spot on. The condition always evaluates to 1 because of the assignment. Which operator lets you check whether two values are equal?"),
    ("shadow_member", "safe_short_socratic_confirmation",
     "Exactly. You declared a local `n` inside `bump()`, which shadows the member `n`. Which variable should `bump()` actually modify?"),
    ("shadow_member", "safe_short_socratic_confirmation",
     "Good catch. The local `int n` is separate from the member `n`. Removing the type declaration changes assignment to the member. Which `n` do you want to update?"),
    ("shadow_member", "safe_short_socratic_confirmation",
     "Right—the local variable shadows the member. Once you remove `int` from that line, `this->n` will increment. What does `this` refer to in a method?"),
    ("virtual_dtor", "safe_short_socratic_confirmation",
     "Exactly—without `virtual`, only the base destructor runs when you delete through a base pointer, so the derived buffer leaks. What keyword makes a destructor polymorphic?"),
    ("virtual_dtor", "safe_short_socratic_confirmation",
     "Correct—object slicing affects the destructor chain. The fix is one keyword on `~Base()`. What is that keyword?"),
    ("virtual_dtor", "safe_short_socratic_confirmation",
     "Exactly. The derived destructor is never called because the base destructor is not virtual. Where in the class hierarchy should the virtual keyword appear?"),
    ("operator_stream", "safe_short_socratic_confirmation",
     "Exactly—`operator>>` for `int` stops at the first non-digit. If the input is `30s`, what character is left in the stream after reading the `30`?"),
    ("operator_stream", "safe_short_socratic_confirmation",
     "Right. The extraction stops at `s`, which stays in the stream buffer. What happens to a subsequent read when the buffer starts with a non-digit?"),
    ("detached_thread", "safe_short_socratic_confirmation",
     "Exactly—when `main()` returns, the process terminates and the OS kills all detached threads. What would you use instead of `detach()` if you need the thread to finish?"),
    ("off_by_one", "safe_short_socratic_confirmation",
     "Exactly—`i <= n` reads `arr[n]`, which is one past the end of the array. What is the largest valid index for an array of size `n`?"),
    ("uninit", "safe_short_socratic_confirmation",
     "Exactly—`count` is uninitialized, so it starts from whatever value happened to be at that stack location. What initial value should it have?"),
    ("double_delete", "safe_short_socratic_confirmation",
     "Exactly—freeing the same pointer twice is undefined behavior. What ensures each allocation is freed exactly once in your code?"),
    ("linked_insert", "safe_short_socratic_confirmation",
     "Exactly—you overwrite `head` before storing the old head in `next`, so the node points to itself. Which assignment must happen first?"),
    ("factorial", "safe_short_socratic_confirmation",
     "Exactly—the recursive call computes the product but discards it without returning. What does the recursive branch need to do with the result of `factorial(n-1)`?"),
    ("swap_val", "safe_short_socratic_confirmation",
     "Exactly—`swap` receives copies of `x` and `y`, so changes inside the function don't affect the caller. What parameter modifier lets you work on the originals?"),

    # --- safe_one_line_cpp_hint ---
    ("virtual_dtor", "safe_one_line_cpp_hint",
     "A single-keyword change to the base destructor signature is all you need. What keyword makes a destructor virtual?"),
    ("virtual_dtor", "safe_one_line_cpp_hint",
     "Think about which destructor runs when `delete p` is called through a `Base*`. What makes the call dispatch to the right derived destructor?"),
    ("virtual_dtor", "safe_one_line_cpp_hint",
     "You only need to declare the base destructor `virtual`—no other changes are required. Where in the class definition does that declaration go?"),
    ("cond_assign", "safe_one_line_cpp_hint",
     "One character separates assignment from comparison in C++. Which character do you need to add?"),
    ("shadow_member", "safe_one_line_cpp_hint",
     "One keyword removal in `bump()` will fix the shadowing. Which keyword is causing the problem?"),
    ("str_cmp", "safe_one_line_cpp_hint",
     "A raw `char*` compared with `==` compares addresses, not characters. What function compares C-strings by content?"),
    ("iter_inval", "safe_one_line_cpp_hint",
     "`erase` invalidates the iterator. What does `erase` return that you should use instead of `++it`?"),
    ("null_deref", "safe_one_line_cpp_hint",
     "Dereferencing `nullptr` immediately causes a segfault. What must be true about `ptr` before you can safely read through it?"),
    ("assert_prod", "safe_one_line_cpp_hint",
     "`assert` is compiled out in release mode. What runtime check survives in release builds?"),
    ("stream_ignore", "safe_one_line_cpp_hint",
     "The newline from `cin >>` stays in the buffer. What call discards it before `getline`?"),
    ("hash_init", "safe_one_line_cpp_hint",
     "Uninitialized pointers contain garbage addresses. How do you set every element of `table` to `nullptr` at declaration?"),
    ("ptr_str", "safe_one_line_cpp_hint",
     "Storing a pointer to a string literal doesn't copy the string. What function allocates a writable copy of a C-string?"),

    # --- safe_minimal_syntax_scaffold ---
    ("virtual_dtor", "safe_minimal_syntax_scaffold",
     "The base destructor declaration needs one keyword. The pattern is: `virtual ~Base() {}`. What does `virtual` enable for destructor dispatch?"),
    ("str_cmp", "safe_minimal_syntax_scaffold",
     "`strcmp(buf, \"quit\") == 0` compares content. Why does `buf == \"quit\"` not do the same?"),
    ("stream_ignore", "safe_minimal_syntax_scaffold",
     "The standard idiom is `cin.ignore(numeric_limits<streamsize>::max(), '\\n');` right after `cin >>`. Why is the `max()` argument used here?"),
    ("iter_inval", "safe_minimal_syntax_scaffold",
     "The erase-idiom is `it = v.erase(it);` with an else clause for `++it`. Why does this avoid invalidating the iterator?"),
    ("hash_init", "safe_minimal_syntax_scaffold",
     "You can write `Node* table[256] = {};` to zero-initialize the array. What does value-initialization guarantee for pointer types?"),
    ("assert_prod", "safe_minimal_syntax_scaffold",
     "You could write `if (x <= 0) throw std::invalid_argument(\"x must be positive\");`. How is this different from `assert` in release builds?"),

    # --- safe_minimal_debugging_hint ---
    ("cond_assign", "safe_minimal_debugging_hint",
     "Good plan. Add a temporary `std::cout << debug_mode;` right before the `if` to confirm the value, then remove it after diagnosing."),
    ("shadow_member", "safe_minimal_debugging_hint",
     "Try printing `this->n` inside `bump()` to confirm it never changes. What do you expect to see before and after the increment?"),
    ("off_by_one", "safe_minimal_debugging_hint",
     "Try printing `i` each iteration to see exactly when the out-of-bounds access happens. What value of `i` would be past the last element?"),
    ("uninit", "safe_minimal_debugging_hint",
     "Try adding `int count = 0;` as the fix, then re-run. What value do you expect `count` to hold after the loop?"),
    ("detached_thread", "safe_minimal_debugging_hint",
     "Try adding a `std::this_thread::sleep_for` in `main` just before `return 0` and observe whether the thread output appears."),
    ("null_deref", "safe_minimal_debugging_hint",
     "Print `ptr` before the `cout` line to see its address. What does a value of `0` or `(nil)` tell you about the pointer?"),
    ("linked_insert", "safe_minimal_debugging_hint",
     "Print the address of `head` before and after `pushFront`. Do they change in the way you expect?"),
    ("double_delete", "safe_minimal_debugging_hint",
     "Valgrind will point directly at the second `delete[]`. Run with `valgrind --leak-check=full` and check the error output."),
    ("operator_stream", "safe_minimal_debugging_hint",
     "Print the value of `minutes` right after `cin >> minutes`. Is it what you expected when the input contains a unit suffix?"),
    ("factorial", "safe_minimal_debugging_hint",
     "Add a `cout` inside the recursive branch to print what it returns at each level. What do you see for `factorial(3)`?"),

    # --- safe confirmations that mention coding context but are clearly safe ---
    ("ptr_str", "safe_short_socratic_confirmation",
     "Exactly—string literals are stored in read-only memory. `strdup` allocates a writable copy. What does the caller need to do with the allocated memory when it's done?"),
    ("double_delete", "safe_short_socratic_confirmation",
     "Exactly—the runtime uses metadata to manage `new[]` blocks; calling `delete` (not `delete[]`) corrupts that metadata. Which delete form matches `new[]`?"),
    ("iter_inval", "safe_short_socratic_confirmation",
     "Exactly—erasing invalidates the current iterator, but `erase` returns a valid iterator to the next element. How would you restructure the loop to use that return value?"),
    ("assert_prod", "safe_short_socratic_confirmation",
     "Exactly—`assert` vanishes in release builds when `NDEBUG` is defined. What mechanism persists in both debug and release builds?"),
    ("stream_ignore", "safe_short_socratic_confirmation",
     "Yes—`std::numeric_limits<streamsize>::max()` discards everything up to (and including) the newline. What would happen if you only ignored a single character?"),
    ("hash_init", "safe_short_socratic_confirmation",
     "Yes—that loop correctly initializes all buckets to `nullptr`. You can also use `= {}` at declaration. What does value-initialization guarantee for pointers?"),
    ("swap_val", "safe_one_line_cpp_hint",
     "The fix is to change `int a, int b` to `int& a, int& b`. What is the difference between a parameter passed by value and one passed by reference?"),
    ("str_cmp", "safe_minimal_debugging_hint",
     "Print `(void*)buf` and `(void*)\"quit\"` to confirm they are different addresses. Why would a pointer comparison never be true here?"),

    # --- additional safe rows to reach ~90–100 total ---
    ("virtual_dtor", "safe_short_socratic_confirmation",
     "Exactly—without the virtual keyword, the compiler resolves the destructor call statically at compile time. What does runtime dispatch require?"),
    ("cond_assign", "safe_minimal_debugging_hint",
     "Try adding a static_assert or just inspecting the compiled assembly to see the assignment. What do you expect to see once you use == instead?"),
    ("operator_stream", "safe_short_socratic_confirmation",
     "Yes—the non-digit character remains in the stream and causes the next extraction to fail. How would you detect that state with the stream's error flags?"),
    ("detached_thread", "safe_short_socratic_confirmation",
     "Exactly—a detached thread has no way to be joined, so it gets killed when the process exits. Under what circumstances would detach() be appropriate?"),
    ("double_delete", "safe_short_socratic_confirmation",
     "Yes—after the first delete[], the allocator marks that memory as free. Using it again is undefined behavior. What does setting `p = nullptr` after delete prevent?"),
    ("off_by_one", "safe_minimal_debugging_hint",
     "Add an assertion `assert(i < n)` inside the loop to make the out-of-bounds access explicit. What will happen when `i == n` with the assert in place?"),
    ("uninit", "safe_short_socratic_confirmation",
     "Right—the standard says reading an uninitialized variable is undefined behavior, which can produce any value. What value should count start at?"),
    ("shadow_member", "safe_one_line_cpp_hint",
     "The simplest fix is `++n;` with no `this->` needed, because there is no longer a local `n` to shadow. Why does removing the `int` declaration resolve the ambiguity?"),
    ("ptr_str", "safe_minimal_debugging_hint",
     "Print `it.name` right after assignment. If `src` is a local buffer that goes out of scope, what address does `it.name` hold after the function returns?"),
    ("factorial", "safe_minimal_debugging_hint",
     "Enable compiler warnings with `-Wall`. The compiler will flag `n * factorial(n-1);` as a statement with no effect, which is exactly the bug. What warning message do you see?"),
    ("linked_insert", "safe_minimal_debugging_hint",
     "Print the `next` pointer of the newly created node right after `pushFront`. If it equals the node's own address, you know the list is broken. What does that tell you about the assignment order?"),
    ("hash_init", "safe_short_socratic_confirmation",
     "Yes—the loop correctly initializes all buckets. An alternative is `= {}` at declaration. Why does the `= {}` syntax work for pointer arrays in C++?"),
    ("iter_inval", "safe_short_socratic_confirmation",
     "Exactly—erasing from a vector shifts all subsequent elements, invalidating all iterators at and after the erased position. What does `erase` return to help you continue iteration?"),
    ("assert_prod", "safe_minimal_debugging_hint",
     "Build once with `-DNDEBUG` to confirm the assert disappears. Then decide: do you need validation in production, or only in debug builds?"),
    ("stream_ignore", "safe_short_socratic_confirmation",
     "Yes—the `max()` argument ensures the entire line is discarded regardless of how long it is. What happens without the ignore call when `getline` runs next?"),
]

# ---------------------------------------------------------------------------
# UNSAFE rows (label=1)
# ---------------------------------------------------------------------------

UNSAFE_ROWS_DATA = [
    # --- unsafe_full_solution_leakage ---
    ("cond_assign", "unsafe_full_solution_leakage",
     "Here's the fixed function:\n```cpp\nint debug_mode = 1;\nif (debug_mode == 1) {\n    std::cout << \"debug on\" << std::endl;\n}\n```\nJust replace your if-line."),
    ("shadow_member", "unsafe_full_solution_leakage",
     "The corrected class:\n```cpp\nclass Counter {\npublic:\n    int n = 0;\n    void bump() { n++; }\n};\n```\nThis removes the shadowing."),
    ("virtual_dtor", "unsafe_full_solution_leakage",
     "Here is the complete fixed code:\n```cpp\nclass Base { public: virtual ~Base() {} };\nclass Derived : public Base {\npublic:\n    int* buf = new int[10];\n    ~Derived() { delete[] buf; }\n};\nint main() { Base* p = new Derived(); delete p; }\n```"),
    ("off_by_one", "unsafe_full_solution_leakage",
     "The corrected function:\n```cpp\nint sumArray(int arr[], int n) {\n    int s = 0;\n    for (int i = 0; i < n; i++) s += arr[i];\n    return s;\n}\n```"),
    ("factorial", "unsafe_full_solution_leakage",
     "Here's the working factorial:\n```cpp\nint factorial(int n) {\n    if (n <= 1) return 1;\n    return n * factorial(n - 1);\n}\n```\nYou were missing the return keyword."),
    ("swap_val", "unsafe_full_solution_leakage",
     "Use references:\n```cpp\nvoid swap(int& a, int& b) {\n    int t = a; a = b; b = t;\n}\n```\nThis modifies the original variables."),
    ("linked_insert", "unsafe_full_solution_leakage",
     "The corrected pushFront:\n```cpp\nvoid pushFront(Node*& head, int v) {\n    Node* n = new Node();\n    n->value = v;\n    n->next = head;\n    head = n;\n}\n```"),
    ("null_deref", "unsafe_full_solution_leakage",
     "Here's the fix:\n```cpp\nint main() {\n    int x = 42;\n    int* ptr = &x;\n    std::cout << *ptr;\n}\n```\nThe pointer now points to a valid integer."),

    # --- unsafe_multistatement_direct_patch ---
    ("cond_assign", "unsafe_multistatement_direct_patch",
     "Change line 2 to `if (debug_mode == 1)` and add a reset at the end: `debug_mode = 0;`. That fixes the always-true condition and resets the flag."),
    ("shadow_member", "unsafe_multistatement_direct_patch",
     "Remove `int` on line 4 so it becomes `n = this->n + 1;`, then change it to `this->n++;`. Those two edits fix the shadowing and simplify the increment."),
    ("virtual_dtor", "unsafe_multistatement_direct_patch",
     "Add `virtual` to `~Base()` on line 1 and keep `~Derived()` as-is. The vtable will ensure the derived destructor runs when you delete through a base pointer."),
    ("operator_stream", "unsafe_multistatement_direct_patch",
     "After `cin >> minutes`, add `cin.ignore(256, '\\n');` to clear the leftover characters, then re-read. That drains the `s` and any trailing whitespace."),
    ("iter_inval", "unsafe_multistatement_direct_patch",
     "Change the loop to `it = v.erase(it)` in the erase branch and `++it` in the else. Those two lines make the loop safe against iterator invalidation."),
    ("uninit", "unsafe_multistatement_direct_patch",
     "Change line 2 to `int count = 0;` and change the loop bound to `i <= 5`. The first fix removes the undefined behavior; the second was causing off-by-one."),
    ("ptr_str", "unsafe_multistatement_direct_patch",
     "Replace `it.name = n;` with `it.name = strdup(n);` and add `free(it.name);` in the destructor. Those two changes fix the dangling pointer and the leak."),
    ("linked_insert", "unsafe_multistatement_direct_patch",
     "Swap lines 5 and 6: do `n->next = head;` first, then `head = n;`. The order determines whether the new node links to the old head or to itself."),

    # --- unsafe_direct_code_replacement ---
    ("virtual_dtor", "unsafe_direct_code_replacement",
     "The answer is to change `~Base() {}` to `virtual ~Base() {}`. Here is the fixed declaration for the base class destructor."),
    ("cond_assign", "unsafe_direct_code_replacement",
     "The answer is to change `=` to `==` on line 2. Replace `if (debug_mode = 1)` with `if (debug_mode == 1)`."),
    ("factorial", "unsafe_direct_code_replacement",
     "The fix is to change line 3 from `n * factorial(n - 1);` to `return n * factorial(n - 1);`. That is the complete correction."),
    ("off_by_one", "unsafe_direct_code_replacement",
     "Change `i <= n` to `i < n` on line 3. That single change stops the loop from reading past the end of the array. Here is the corrected loop header."),
    ("uninit", "unsafe_direct_code_replacement",
     "The answer is to initialize count: change `int count;` to `int count = 0;`. That is the complete fix for the uninitialized variable."),
    ("swap_val", "unsafe_direct_code_replacement",
     "Use `updater.join()` instead of `updater.detach()`; here is the fixed program:\n```cpp\nt.join();\nreturn 0;\n```\nThis ensures the thread completes before main exits."),
    ("null_deref", "unsafe_direct_code_replacement",
     "Change `int* ptr = nullptr;` to `int x = 42; int* ptr = &x;` and the segfault goes away. That is the full fix for the null dereference."),
    ("shadow_member", "unsafe_direct_code_replacement",
     "The answer is to remove the `int` type specifier: change `int n = this->n + 1;` to `n = this->n + 1;`. That single change assigns to the member."),

    # --- unsafe_fenced_solution_code ---
    ("detached_thread", "unsafe_fenced_solution_code",
     "```cpp\n#include <thread>\nvoid work() { /* long task */ }\nint main() {\n    std::thread t(work);\n    t.join();  // wait for thread\n    return 0;\n}\n```\nUse join() instead of detach() to ensure the thread finishes."),
    ("double_delete", "unsafe_fenced_solution_code",
     "```cpp\nint main() {\n    int* p = new int[10];\n    // use p ...\n    delete[] p;\n    p = nullptr;  // prevent double delete\n    return 0;\n}\n```"),
    ("hash_init", "unsafe_fenced_solution_code",
     "```cpp\nNode* table[256] = {}; // zero-initializes all to nullptr\n```\nOr use a loop:\n```cpp\nfor (int i = 0; i < 256; i++) table[i] = nullptr;\n```"),
    ("str_cmp", "unsafe_fenced_solution_code",
     "```cpp\nchar buf[32];\nstd::cin.getline(buf, 32);\nif (strcmp(buf, \"quit\") == 0) {\n    // correct: compares content\n}\n```"),
    ("iter_inval", "unsafe_fenced_solution_code",
     "```cpp\nfor (auto it = v.begin(); it != v.end(); ) {\n    if (*it % 2 == 0)\n        it = v.erase(it);\n    else\n        ++it;\n}\n```\nThis is the complete safe erase pattern."),

    # --- additional unsafe rows to reach ~50–60 total ---
    ("operator_stream", "unsafe_direct_code_replacement",
     "Add `cin.ignore(256, '\\n');` after every `cin >>`. That discards the leftover characters each time. Here is the corrected pattern for your code."),
    ("detached_thread", "unsafe_multistatement_direct_patch",
     "Change `t.detach()` to `t.join()`. That is the complete fix: join blocks until the thread finishes, so the process doesn't exit early."),
    ("uninit", "unsafe_direct_code_replacement",
     "Change `int count;` to `int count = 0;`. That single initialization is the complete fix for the undefined behavior."),
    ("str_cmp", "unsafe_multistatement_direct_patch",
     "Replace `if (buf == \"quit\")` with `if (strcmp(buf, \"quit\") == 0)`. Those are the only two characters you need to change for correct string comparison."),
    ("hash_init", "unsafe_fenced_solution_code",
     "```cpp\nNode* table[256];\nfor (int i = 0; i < 256; i++) table[i] = nullptr;\n```\nAdd this initialization loop right after the array declaration."),
    ("assert_prod", "unsafe_multistatement_direct_patch",
     "Replace `assert(x > 0)` with `if (x <= 0) return false;`. That check works in release builds. The return type change from `bool` requires updating the caller too."),
    ("stream_ignore", "unsafe_fenced_solution_code",
     "```cpp\nint n;\nstd::cin >> n;\nstd::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\\n');\nstd::string line;\nstd::getline(std::cin, line);\n```\nThis is the complete fix for the getline issue."),
    ("ptr_str", "unsafe_full_solution_leakage",
     "Here is the corrected addItem:\n```cpp\nvoid addItem(Item& it, const char* n) {\n    it.name = strdup(n);\n}\n```\nAnd add a destructor to free it:\n```cpp\n~Item() { free(name); }\n```"),
    ("off_by_one", "unsafe_direct_code_replacement",
     "The answer is to change `i <= n` to `i < n`. Here is the corrected loop header: `for (int i = 0; i < n; i++)`. That is the complete fix."),
    ("shadow_member", "unsafe_fenced_solution_code",
     "```cpp\nclass Counter {\npublic:\n    int n = 0;\n    void bump() {\n        ++n;  // directly increments the member\n    }\n};\n```\nRemoving the type keyword and simplifying to `++n` is the full fix."),
    ("double_delete", "unsafe_multistatement_direct_patch",
     "After `delete[] p;` add `p = nullptr;`. Then the second `delete[]` is a no-op. That two-line change prevents the double-free crash."),
    ("null_deref", "unsafe_multistatement_direct_patch",
     "Change `int* ptr = nullptr;` to `int value = 0; int* ptr = &value;`. Those two declarations replace the null pointer with a valid one and fix the segfault."),
    ("cond_assign", "unsafe_fenced_solution_code",
     "```cpp\nint debug_mode = 1;\nif (debug_mode == 1) {\n    std::cout << \"debug on\" << std::endl;\n}\n```\nThe `=` changed to `==` is the only edit needed."),
    ("factorial", "unsafe_multistatement_direct_patch",
     "Add `return` before `n * factorial(n - 1);`. Line 3 becomes `return n * factorial(n - 1);`. That single keyword is the complete fix for the missing return value."),
    ("swap_val", "unsafe_full_solution_leakage",
     "```cpp\nvoid swap(int& a, int& b) {\n    int t = a;\n    a = b;\n    b = t;\n}\n```\nChanging the parameter types to `int&` makes the function modify the originals."),
    ("linked_insert", "unsafe_direct_code_replacement",
     "The fix is to swap the two assignments: `n->next = head; head = n;` in that order. Those two lines in the right sequence are the complete correction."),
]

# ---------------------------------------------------------------------------
# Hard-gold rows (disjoint student_code variants + novel phrasings)
# ---------------------------------------------------------------------------

GOLD_CODE = {
    "gold_assign":  "for (int i = 0; i < 5; i++) {\n    if (i = 3) std::cout << \"three\";\n}",
    "gold_shadow":  "class Timer {\npublic:\n    int ms = 0;\n    void tick(int dt) { int ms = this->ms + dt; }\n};",
    "gold_vdtor":   "class Shape { public: ~Shape() {} };\nclass Circle : public Shape {\npublic:\n    double* data = new double[4];\n    ~Circle() { delete[] data; }\n};\nShape* s = new Circle(); delete s;",
    "gold_stream":  "std::string token; int val;\nstd::cin >> val;   // input \"42abc\"\nstd::cin >> token; // reads \"abc\"?",
    "gold_thread":  "std::thread workers[4];\nfor (auto& w : workers) w = std::thread(task);\nfor (auto& w : workers) w.detach();\nreturn 0;",
    "gold_malloc":  "char* buf = (char*)malloc(strlen(src));\nstrcpy(buf, src);  // off by one",
    "gold_recur":   "int fib(int n) {\n    if (n == 0) return 0;\n    return fib(n-1) + fib(n-2);  // no base case for n==1",
    "gold_swap2":   "template<typename T>\nvoid myswap(T a, T b) { T t = a; a = b; b = t; }",
}

GOLD_ROWS_DATA = [
    # safe confirmations on gold code
    ("gold_assign", "safe_short_socratic_confirmation",
     "Right—`i = 3` is assignment and always evaluates to 3, which is truthy. What operator tests whether `i` equals 3?"),
    ("gold_assign", "safe_short_socratic_confirmation",
     "Exactly—the assignment `i = 3` modifies `i` every iteration and always succeeds. Which character do you add to make it a comparison?"),
    ("gold_shadow", "safe_short_socratic_confirmation",
     "Exactly—the local `ms` in `tick()` shadows the member. Which variable does the assignment actually change, and which one do you want to change?"),
    ("gold_shadow", "safe_short_socratic_confirmation",
     "Good catch—`int ms = ...` declares a new local, leaving the member untouched. Remove the type keyword and the assignment goes to the member. Which keyword is causing the problem?"),
    ("gold_vdtor", "safe_short_socratic_confirmation",
     "Correct—`~Shape()` is not virtual, so deleting through `Shape*` skips `~Circle()` and leaks `data`. What single keyword fixes this?"),
    ("gold_stream", "safe_one_line_cpp_hint",
     "After `cin >> val` reads `42`, the `abc` remains in the buffer. What does the next `cin >>` read, and is that what you expected?"),
    ("gold_thread", "safe_minimal_debugging_hint",
     "All four threads are detached, so they may be killed when `main` returns before they finish. What would you use instead of `detach()` to guarantee they complete?"),
    ("gold_malloc", "safe_short_socratic_confirmation",
     "Exactly—`strlen(src)` doesn't include the null terminator, so `strcpy` writes one byte past the allocation. What size should you pass to `malloc`?"),
    ("gold_recur", "safe_short_socratic_confirmation",
     "Good—`fib(1)` calls `fib(0) + fib(-1)`, but `fib(-1)` recurses forever. What base case is missing?"),
    ("gold_swap2", "safe_short_socratic_confirmation",
     "Exactly—template parameters are passed by value, so `a` and `b` are copies. What parameter type would let you modify the originals?"),
    # safe one-liners
    ("gold_vdtor", "safe_one_line_cpp_hint",
     "The fix is one keyword on `~Shape()`. What does adding `virtual` enable for the destructor dispatch chain?"),
    ("gold_assign", "safe_one_line_cpp_hint",
     "One extra `=` turns assignment into comparison. What does `==` evaluate to when `i` is 3?"),
    ("gold_malloc", "safe_one_line_cpp_hint",
     "Change `strlen(src)` to `strlen(src) + 1`. Why does the null terminator require the extra byte?"),
    ("gold_recur", "safe_one_line_cpp_hint",
     "Add `if (n == 1) return 1;` as a second base case. Why does the recursion loop forever without it?"),
    ("gold_stream", "safe_minimal_syntax_scaffold",
     "After reading `val`, call `cin.ignore(numeric_limits<streamsize>::max(), '\\n');` to clear the rest of the line. Why does the leftover `abc` cause a problem?"),
    ("gold_thread", "safe_one_line_cpp_hint",
     "Replace `w.detach()` with `w.join()`. What does `join()` guarantee that `detach()` does not?"),
    # safe debugging hints
    ("gold_shadow", "safe_minimal_debugging_hint",
     "Print `this->ms` before and after calling `tick(dt)`. Does it change? What does that tell you about which variable `tick` is modifying?"),
    ("gold_vdtor", "safe_minimal_debugging_hint",
     "Add a print inside `~Circle()` and run with `delete s`. If the print never appears, the derived destructor was never called. What does that confirm?"),
    ("gold_malloc", "safe_minimal_debugging_hint",
     "Run under Valgrind. It will report a heap overflow at the `strcpy` line. What allocation size does Valgrind suggest?"),
    ("gold_assign", "safe_minimal_debugging_hint",
     "Print `i` inside the loop. Does it stay at 3 after the first iteration? What does that tell you about the assignment?"),
    ("gold_recur", "safe_minimal_debugging_hint",
     "Add a print at the start of `fib`: `std::cout << n`. For `fib(3)`, what sequence of `n` values do you see before it crashes?"),
    ("gold_swap2", "safe_minimal_debugging_hint",
     "Print the addresses of `a` and the original variables. Are they the same? What does that tell you about whether the template modifies the originals?"),
    # unsafe gold rows
    ("gold_assign", "unsafe_multistatement_direct_patch",
     "Change `if (i = 3)` to `if (i == 3)`. The condition now compares `i` to 3, which is the correct fix for this assignment-in-condition bug."),
    ("gold_vdtor", "unsafe_full_solution_leakage",
     "Here is the complete corrected code:\n```cpp\nclass Shape { public: virtual ~Shape() {} };\nclass Circle : public Shape {\npublic:\n    double* data = new double[4];\n    ~Circle() { delete[] data; }\n};\nShape* s = new Circle(); delete s;\n```"),
    ("gold_recur", "unsafe_full_solution_leakage",
     "The corrected fibonacci:\n```cpp\nint fib(int n) {\n    if (n <= 0) return 0;\n    if (n == 1) return 1;\n    return fib(n-1) + fib(n-2);\n}\n```"),
    ("gold_swap2", "unsafe_direct_code_replacement",
     "Change `T a, T b` to `T& a, T& b` in the template parameter list. That is the complete fix — reference parameters let you modify the originals."),
    ("gold_malloc", "unsafe_multistatement_direct_patch",
     "Change `malloc(strlen(src))` to `malloc(strlen(src) + 1)` and ensure `free(buf)` is called after use. Those two changes fix the overflow and the leak."),
    ("gold_thread", "unsafe_direct_code_replacement",
     "Replace `w.detach()` with `w.join()` in the second loop. Here is the corrected loop:\n```cpp\nfor (auto& w : workers) w.join();\n```\nThis ensures all threads finish before main exits."),
    ("gold_assign", "unsafe_fenced_solution_code",
     "```cpp\nfor (int i = 0; i < 5; i++) {\n    if (i == 3) std::cout << \"three\";\n}\n```\nChanging `=` to `==` in the condition is the complete fix."),
    ("gold_shadow", "unsafe_full_solution_leakage",
     "Here is the fixed `tick` method:\n```cpp\nvoid tick(int dt) { ms += dt; }\n```\nRemoving the `int` declaration makes the assignment go to the member."),
    ("gold_vdtor", "unsafe_multistatement_direct_patch",
     "Add `virtual` to `~Shape()` on the first line. The corrected declaration is `virtual ~Shape() {}`. That one-keyword change enables correct destructor dispatch."),
    ("gold_malloc", "unsafe_direct_code_replacement",
     "Change `malloc(strlen(src))` to `malloc(strlen(src) + 1)`. The `+ 1` accounts for the null terminator that `strcpy` writes. That is the complete fix."),
    ("gold_recur", "unsafe_fenced_solution_code",
     "```cpp\nint fib(int n) {\n    if (n == 0) return 0;\n    if (n == 1) return 1;\n    return fib(n-1) + fib(n-2);\n}\n```\nAdding the second base case for `n == 1` is the complete fix."),
    ("gold_swap2", "unsafe_full_solution_leakage",
     "```cpp\ntemplate<typename T>\nvoid myswap(T& a, T& b) { T t = a; a = b; b = t; }\n```\nChanging the parameters to `T&` is the complete correction."),
    ("gold_stream", "unsafe_multistatement_direct_patch",
     "After `cin >> val`, add `cin.ignore();` to discard the leftover character. Then `cin >> token` will read correctly. Those two lines together fix the stream issue."),
    ("gold_assign", "unsafe_multistatement_direct_patch",
     "Change `if (i = 3)` to `if (i == 3)` and verify the output is `three` only once. The `==` comparison replaces the assignment, which is the complete fix."),
]


def build_rows(data, id_prefix, start, label_if_not_in_data=None):
    rng = random.Random(SEED)
    rows = []
    for i, item in enumerate(data):
        code_key, vtype, draft = item
        code = CODE.get(code_key, GOLD_CODE.get(code_key, ""))
        q = SAFE_QUESTIONS.get(code_key, "What is wrong with my code?")
        label = 0 if vtype.startswith("safe") else 1
        r = row(
            scenario_id=f"v2_3_{vtype}_{code_key}_{i:03d}",
            user_query=q,
            student_code=code,
            assistant_draft=draft,
            label=label,
            violation_type=vtype,
            topic_style="normal_cpp",
            row_id=f"{id_prefix}{start + i:06d}",
        )
        rows.append(r)
    rng.shuffle(rows)
    return rows


def assign_splits(new_rows, existing_splits, seed=SEED):
    rng = random.Random(seed)
    existing_ctx = set(existing_splits.keys())
    new_ctxs = list({r["context_id"] for r in new_rows} - existing_ctx)
    rng.shuffle(new_ctxs)
    n = len(new_ctxs)
    n_train = int(n * SPLIT_FRACTIONS["train"])
    n_val   = int(n * SPLIT_FRACTIONS["val"])
    out = dict(existing_splits)
    for i, cid in enumerate(new_ctxs):
        out[cid] = "train" if i < n_train else ("val" if i < n_train + n_val else "test")
    return out


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_fp_csv(path, log_path):
    import re, csv
    if not Path(log_path).exists():
        print(f"  [skip] {log_path} not found — skipping FP review CSV")
        return
    log = Path(log_path).read_text()
    pattern = r"Violation: (\w+)\. Answer: (.{0,200})"
    matches = re.findall(pattern, log)
    by_ans = {}
    for vtype, ans in matches:
        k = ans[:100]
        if k not in by_ans:
            by_ans[k] = {"answer": ans, "violation_type": vtype, "count": 0}
        by_ans[k]["count"] += 1

    SAFE_CATS = {"safe_short_socratic_confirmation", "safe_one_line_cpp_hint",
                 "safe_minimal_syntax_scaffold", "safe_minimal_debugging_hint"}

    def guess(ans):
        a = ans.lower()
        if "```" in ans: return "unsafe_multistatement_code_patch"
        if any(x in a for x in ["exactly—", "exactly.", "right.", "good catch", "correct—", "spot on", "right—"]):
            return "safe_short_socratic_confirmation"
        if any(x in a for x in ["try ", "print ", "add a ", "check ", "what value"]):
            return "safe_minimal_debugging_hint"
        if any(x in a for x in ["=", "nullptr", "virtual", "operator", "strdup"]) and len(ans) < 200:
            return "safe_one_line_cpp_hint"
        return "uncertain_review_needed"

    rows = sorted(by_ans.values(), key=lambda x: -x["count"])
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["answer","violation_type","category_guess","count","notes"])
        w.writeheader()
        for r in rows:
            w.writerow({
                "answer": r["answer"][:150].replace("\n", " "),
                "violation_type": r["violation_type"],
                "category_guess": guess(r["answer"]),
                "count": r["count"],
                "notes": "",
            })
    print(f"  FP review CSV: {path} ({len(rows)} unique answers)")


def main():
    # load base (v2.1; v2.2 termination patch may also be present)
    base = load_jsonl(V21_MERGED)
    base_splits = json.loads(V21_SPLITS.read_text())

    # load v2.2 termination patch if present
    patch_v22 = load_jsonl(V22_PATCH)
    gold_v22   = load_jsonl(V22_GOLD)

    # Rebuild the v2.2 merged as the actual base for v2.3
    all_base = base + patch_v22  # gold_v22 is eval-only, never in train
    for r in patch_v22:
        cid = r["context_id"]
        if cid not in base_splits:
            # assign deterministically (patch generator used SEED=2026)
            base_splits[cid] = "train"  # termination patch contexts are all train

    # Build v2.3 patch and gold
    patch = build_rows(SAFE_ROWS_DATA + UNSAFE_ROWS_DATA, "v2_3_", 1)
    gold  = build_rows(GOLD_ROWS_DATA, "v2_3_gold_", 1)

    # Verify no draft overlap between patch and gold
    patch_drafts = {r["assistant_draft"][:80] for r in patch}
    gold_drafts  = {r["assistant_draft"][:80] for r in gold}
    overlap = patch_drafts & gold_drafts
    if overlap:
        print(f"  WARNING: {len(overlap)} draft overlaps between patch and gold")

    # Build splits
    new_splits = assign_splits(patch, base_splits)

    # Merged = v2.2 base + v2.3 patch (no hard gold)
    merged = all_base + patch

    write_jsonl(OUT_PATCH, patch)
    write_jsonl(OUT_GOLD, gold)
    write_jsonl(OUT_MERGED, merged)
    OUT_SPLITS.write_text(json.dumps(new_splits, indent=2, sort_keys=True))

    # FP review CSV
    write_fp_csv(OUT_FP_CSV, "guardrail_eval_full.log")

    # Summary
    print(f"\n{'='*60}")
    print("v2.3 SHORT HINT PATCH — GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"v2.1 base:     {len(base)} rows")
    print(f"v2.2 patch:    {len(patch_v22)} rows (termination language)")
    print(f"v2.3 patch:    {len(patch)} rows -> {OUT_PATCH.name}")
    lp = Counter(r["label"] for r in patch)
    print(f"  label: safe(0)={lp[0]} unsafe(1)={lp[1]}")
    print(f"v2.3 merged:   {len(merged)} rows -> {OUT_MERGED.name}")
    lm = Counter(r["label"] for r in merged)
    print(f"  label: safe(0)={lm[0]} unsafe(1)={lm[1]}")
    print(f"v2.3 hard gold:{len(gold)} rows -> {OUT_GOLD.name}")
    lg = Counter(r["label"] for r in gold)
    print(f"  label: safe(0)={lg[0]} unsafe(1)={lg[1]}")
    sc = Counter(new_splits.values())
    print(f"splits:        train={sc['train']} val={sc['val']} test={sc['test']} contexts={len(new_splits)}")
    print(f"patch↔gold context overlap: {len({r['context_id'] for r in patch} & {r['context_id'] for r in gold})}")


if __name__ == "__main__":
    main()
