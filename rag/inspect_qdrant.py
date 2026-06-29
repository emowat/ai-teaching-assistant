"""Quick inspection tool for Qdrant local storage."""
from qdrant_client import QdrantClient
import os

QDRANT_PATH = os.path.join(os.path.dirname(__file__), "..", "qdrant_local_data")

client = QdrantClient(path=QDRANT_PATH)
collections = client.get_collections()

print(f"{'='*60}")
print(f"Qdrant local @ {QDRANT_PATH}")
print(f"{'='*60}\n")

for c in collections.collections:
    info = client.get_collection(c.name)
    n = info.points_count
    dim = info.config.params.vectors.size
    print(f"--- {c.name} ({n} vectors, {dim}-dim) ---")

    points, _ = client.scroll(collection_name=c.name, limit=3, with_payload=True, with_vectors=False)
    for pt in points:
        p = pt.payload
        print(f"  [{p.get('source_type', '?')}] {p.get('topic', '')}")
        print(f"    {p.get('content', '')[:150]}")
    if n > 3:
        # Show type breakdown
        from collections import Counter
        type_counts = Counter()
        offset = None
        while True:
            pts, offset = client.scroll(c.name, limit=500, offset=offset, with_payload=True, with_vectors=False)
            for pt in pts:
                type_counts[pt.payload.get("source_type", "?")] += 1
            if offset is None:
                break
        print(f"\n  Source type breakdown:")
        for st, cnt in type_counts.most_common():
            print(f"    {st}: {cnt}")
    print()

client.close()
