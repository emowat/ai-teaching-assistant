"""CLI entrypoints for idempotent and destructive Qdrant indexing flows."""

from __future__ import annotations

import argparse
import json

from rag_eng.indexing import ensure_index, rebuild_index


def main() -> None:
    """Parse CLI arguments and run the selected indexing command."""
    parser = argparse.ArgumentParser(description="rag_eng indexing utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "ensure-index", help="Create the index if missing and upsert documents."
    )
    subparsers.add_parser("rebuild-index", help="Delete and rebuild the entire index.")

    args = parser.parse_args()
    if args.command == "ensure-index":
        result = ensure_index()
    else:
        result = rebuild_index()

    print(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    main()
