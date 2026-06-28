from __future__ import annotations

from pathlib import Path


def test_gradio_url_helper_uses_canonical_trailing_slash() -> None:
    source = Path("frontend/src/api/gradioApi.ts").read_text(encoding="utf-8")
    normalized = "".join(source.split())

    assert 'return`${base.replace(/\\/$/,"")}/gradio/`;' in normalized
