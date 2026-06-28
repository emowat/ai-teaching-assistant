from __future__ import annotations

from pathlib import Path


def test_rag_eng_startup_enables_proxy_headers() -> None:
    script = Path("deploy/scripts/rag-eng-startup.sh").read_text(encoding="utf-8")
    assert "--proxy-headers" in script
    assert "--forwarded-allow-ips '*'" in script


def test_dockerfile_enables_proxy_headers() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert '"--proxy-headers"' in dockerfile
    assert '"--forwarded-allow-ips",' in dockerfile
    assert '"*"' in dockerfile
