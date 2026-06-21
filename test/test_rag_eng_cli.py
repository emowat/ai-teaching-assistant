from __future__ import annotations

import json
from types import SimpleNamespace

from rag.course_registry import CourseRoute
from rag.schemas import CourseSource

import rag_eng.cli as cli


class _FakeRegistry:
    def __init__(self, runtime, database_url=None):
        self.runtime = runtime
        self.database_url = database_url

    def resolve(self, *, course_id=None, course_source=None):
        self.course_id = course_id
        self.course_source = course_source
        if course_id:
            return CourseRoute(
                course_id="mit14",
                course_source=CourseSource.MIT_14,
                collection_name="mit14_course_db",
            )
        return CourseRoute(
            course_id="cs50",
            course_source=CourseSource.CS50,
            collection_name="cs50_course_db",
        )


def test_resolve_course_command_uses_database_url_override(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def _factory(runtime, database_url=None):
        registry = _FakeRegistry(runtime, database_url)
        captured["registry"] = registry
        return registry

    monkeypatch.setattr(cli, "CourseRegistry", _factory)
    monkeypatch.setattr(
        cli,
        "get_runtime_config",
        lambda: SimpleNamespace(collection_mit13="mit13_course"),
    )

    cli.main(
        [
            "resolve-course",
            "--course-id",
            "mit-14",
            "--database-url",
            "postgresql://example",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    registry = captured["registry"]

    assert payload == {
        "course_id": "mit14",
        "course_source": "mit14",
        "collection_name": "mit14_course_db",
    }
    assert registry.database_url == "postgresql://example"
    assert registry.course_id == "mit-14"
    assert registry.course_source is None


def test_resolve_course_command_uses_legacy_course_source(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def _factory():
        registry = _FakeRegistry(SimpleNamespace(collection_mit13="mit13_course"))
        captured["registry"] = registry
        return registry

    monkeypatch.setattr(cli, "get_course_registry", _factory)

    cli.main(["resolve-course", "--course-source", "cs50"])

    payload = json.loads(capsys.readouterr().out)
    registry = captured["registry"]

    assert payload == {
        "course_id": "cs50",
        "course_source": "cs50",
        "collection_name": "cs50_course_db",
    }
    assert registry.database_url is None
    assert registry.course_id is None
    assert registry.course_source is CourseSource.CS50
