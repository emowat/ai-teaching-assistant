from __future__ import annotations

from rag_eng import indexing


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_ensure_index_uses_non_destructive_flow(monkeypatch) -> None:
    client = FakeClient()
    recreate_flags: list[bool] = []

    monkeypatch.setattr(indexing, "create_qdrant_client", lambda: client)
    monkeypatch.setattr(
        indexing,
        "_ensure_collection",
        lambda current_client, recreate: recreate_flags.append(recreate) or False,
    )
    monkeypatch.setattr(indexing, "_ensure_payload_indexes", lambda current_client: None)
    monkeypatch.setattr(indexing, "_build_points", lambda: ["point-a", "point-b"])
    monkeypatch.setattr(indexing, "_upsert_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_ensure_guidelines_collection", lambda current_client, recreate: False)
    monkeypatch.setattr(indexing, "_build_guidelines_points", lambda: ["guideline-a"])
    monkeypatch.setattr(indexing, "_upsert_guidelines_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_ensure_harvard_collection", lambda current_client, recreate: False)
    monkeypatch.setattr(indexing, "_build_harvard_points", lambda: ["harvard-a"])
    monkeypatch.setattr(indexing, "_upsert_harvard_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_collection_name", lambda: "capstone")

    result = indexing.ensure_index()

    assert recreate_flags == [False]
    assert result.collection_name == "capstone"
    assert result.indexed_documents == 4
    assert result.created_collection is False
    assert client.closed is True


def test_rebuild_index_uses_destructive_flow(monkeypatch) -> None:
    client = FakeClient()
    recreate_flags: list[bool] = []

    monkeypatch.setattr(indexing, "create_qdrant_client", lambda: client)
    monkeypatch.setattr(
        indexing,
        "_ensure_collection",
        lambda current_client, recreate: recreate_flags.append(recreate) or True,
    )
    monkeypatch.setattr(indexing, "_ensure_payload_indexes", lambda current_client: None)
    monkeypatch.setattr(indexing, "_build_points", lambda: ["point-a"])
    monkeypatch.setattr(indexing, "_upsert_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_ensure_guidelines_collection", lambda current_client, recreate: True)
    monkeypatch.setattr(indexing, "_build_guidelines_points", lambda: ["guideline-a"])
    monkeypatch.setattr(indexing, "_upsert_guidelines_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_ensure_harvard_collection", lambda current_client, recreate: True)
    monkeypatch.setattr(indexing, "_build_harvard_points", lambda: ["harvard-a"])
    monkeypatch.setattr(indexing, "_upsert_harvard_points", lambda current_client, points: len(points))
    monkeypatch.setattr(indexing, "_collection_name", lambda: "capstone")

    result = indexing.rebuild_index()

    assert recreate_flags == [True]
    assert result.collection_name == "capstone"
    assert result.indexed_documents == 3
    assert result.created_collection is True
    assert client.closed is True
