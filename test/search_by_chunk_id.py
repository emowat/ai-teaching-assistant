"""
按 chunk_id 搜索 cpp_guidelines 和 harvard_cs50 的 chunk 内容。
直接从 raw_data/ JSON 文件加载（复用 labeling_chunks.py 的函数），无需 Qdrant。
同时从 eval_queries.jsonl 加载 student_message 和 golden_answer。

用法：
    python scripts/search_by_chunk_id.py <your_chunk_ids.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.experiments.labeling_chunks import (
    load_cpp_guidelines,
    load_harvard_notes,
    load_harvard_transcripts,
)

EVAL_QUERIES_PATH = Path(__file__).resolve().parent.parent / "rag" / "experiments" / "outputs" / "eval_queries_cs50.jsonl"


def load_eval_queries(path: Path) -> dict[str, dict]:
    """从 eval_queries.jsonl 加载 query_id → {student_message, golden_answer, ...}"""
    if not path.exists():
        print(f"Warning: eval_queries.jsonl not found at {path}")
        return {}
    queries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        queries[rec["query_id"]] = rec
    return queries


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/search_by_chunk_id.py <chunk_ids.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)

    data = json.loads(input_path.read_text())
    eval_queries = load_eval_queries(EVAL_QUERIES_PATH)
    print(f"Loaded {len(eval_queries)} eval queries from eval_queries.jsonl\n")

    # 直接从 raw_data 加载三个来源的 chunk
    print("Loading chunks from raw_data/ ...")
    guidelines = load_cpp_guidelines("raw_data/cppcoreguidelines/cppcoreguidelines.json")
    harvard_notes = load_harvard_notes("raw_data")
    harvard_transcripts = load_harvard_transcripts("raw_data")

    all_chunks: dict[str, dict] = {}
    for c in guidelines + harvard_notes + harvard_transcripts:
        all_chunks[c.chunk_id] = {
            "content": c.content,
            "week": c.week,
            "category": c.category,
            "source_file": c.source_file,
            "source_domain": c.source_domain,
        }

    print(f"Loaded: {len(guidelines)} guidelines, {len(harvard_notes)} notes, "
          f"{len(harvard_transcripts)} transcripts → {len(all_chunks)} total chunks\n")

    output = {}
    for query_id, chunk_ids in data.items():
        # 查 eval_queries 获取 student_message / golden_answer
        qinfo = eval_queries.get(query_id, {})
        student_message = qinfo.get("student_message", "")
        golden_answer = qinfo.get("golden_answer", "")

        # 查 chunk
        found = {}
        missing = []
        for cid in chunk_ids:
            if cid in all_chunks:
                found[cid] = all_chunks[cid]
            else:
                missing.append(cid)

        entry = {
            "student_message": student_message,
            "golden_answer": golden_answer,
            "week": qinfo.get("week"),
            "mode": qinfo.get("mode"),
            "topic": qinfo.get("topic"),
            "found_chunks": found,
            "missing_chunk_ids": missing,
        }
        output[query_id] = entry

        # 打印
        print(f"{'=' * 70}")
        print(f"Query: {query_id}  week={qinfo.get('week')}  mode={qinfo.get('mode')}")
        print(f"       ({len(chunk_ids)} chunk_ids) → hit {len(found)}, miss {len(missing)}")
        print(f"{'=' * 70}")

        msg_preview = student_message[:120].replace("\n", "\\n")
        print(f"\n  student_message: {msg_preview}...")
        answer_preview = golden_answer[:120].replace("\n", "\\n")
        print(f"  golden_answer:   {answer_preview}...")

        for cid, info in found.items():
            content_preview = info["content"][:150].replace("\n", "\\n")
            print(f"\n  [{cid}]")
            print(f"  week={info['week']}  category={info['category']}  "
                  f"source={info['source_domain']}")
            print(f"  content: {content_preview}...")

        if missing:
            print("\n  [NOT FOUND]:")
            for m in missing:
                print(f"    {m}")

    # 保存结果
    out_path = input_path.with_suffix(".results.json")
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    main()
