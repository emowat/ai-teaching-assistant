from __future__ import annotations

import tarfile
from pathlib import Path

from deploy.restore_input_guardrail_checkpoint import (
    extract_checkpoint_tarball,
    parse_s3_uri,
    restore_checkpoint_from_s3,
)


def _write_checkpoint_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text('{"architectures": ["RobertaForSequenceClassification"]}')
    (root / "tokenizer.json").write_text('{"version": "1.0"}')
    (root / "model.safetensors").write_text("weights")
    return root


def test_parse_s3_uri() -> None:
    bucket, key = parse_s3_uri("s3://codingrabbit-data-dev/models/input_codebert_v1/")
    assert bucket == "codingrabbit-data-dev"
    assert key == "models/input_codebert_v1/"


def test_restore_checkpoint_from_s3_syncs_prefix(tmp_path, monkeypatch) -> None:
    source = _write_checkpoint_tree(tmp_path / "source")
    prefix = "models/input_codebert_v1/"
    output_dir = tmp_path / "output"

    class _FakePaginator:
        def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
            assert Bucket == "codingrabbit-data-dev"
            assert Prefix == prefix
            return [
                {
                    "Contents": [
                        {"Key": f"{prefix}config.json"},
                        {"Key": f"{prefix}tokenizer.json"},
                        {"Key": f"{prefix}model.safetensors"},
                    ]
                }
            ]

    class _FakeS3Client:
        def get_paginator(self, name: str):
            assert name == "list_objects_v2"
            return _FakePaginator()

        def download_file(self, bucket: str, key: str, destination: str):
            assert bucket == "codingrabbit-data-dev"
            relative = key[len(prefix):]
            src = source / relative
            Path(destination).write_bytes(src.read_bytes())

    class _FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def client(self, name: str):
            assert name == "s3"
            return _FakeS3Client()

    monkeypatch.setattr(
        "deploy.restore_input_guardrail_checkpoint.boto3.Session",
        _FakeSession,
    )

    restored = restore_checkpoint_from_s3(
        "s3://codingrabbit-data-dev/models/input_codebert_v1/",
        output_dir,
    )

    assert restored == output_dir.resolve()
    assert (output_dir / "config.json").exists()
    assert (output_dir / "tokenizer.json").exists()
    assert (output_dir / "model.safetensors").exists()


def test_restore_checkpoint_from_s3_extracts_tarball_inside_prefix(
    tmp_path,
    monkeypatch,
) -> None:
    source_dir = _write_checkpoint_tree(tmp_path / "source")
    source_tarball = tmp_path / "source.tar.gz"
    prefix = "models/guardrails/input_codebert_v1/"
    output_dir = tmp_path / "output"

    with tarfile.open(source_tarball, "w:gz") as tar:
        for path in sorted(source_dir.iterdir()):
            tar.add(path, arcname=path.name)

    class _FakePaginator:
        def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
            assert Bucket == "codingrabbit-data-dev"
            assert Prefix == prefix
            return [
                {
                    "Contents": [
                        {"Key": f"{prefix}model.tar.gz"},
                    ]
                }
            ]

    class _FakeS3Client:
        def get_paginator(self, name: str):
            assert name == "list_objects_v2"
            return _FakePaginator()

        def download_file(self, bucket: str, key: str, destination: str):
            assert bucket == "codingrabbit-data-dev"
            assert key == f"{prefix}model.tar.gz"
            Path(destination).write_bytes(source_tarball.read_bytes())

    class _FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def client(self, name: str):
            assert name == "s3"
            return _FakeS3Client()

    monkeypatch.setattr(
        "deploy.restore_input_guardrail_checkpoint.boto3.Session",
        _FakeSession,
    )

    restored = restore_checkpoint_from_s3(
        "s3://codingrabbit-data-dev/models/guardrails/input_codebert_v1/",
        output_dir,
    )

    assert restored == output_dir.resolve()
    assert (output_dir / "config.json").exists()
    assert (output_dir / "tokenizer.json").exists()
    assert (output_dir / "model.safetensors").exists()


def test_extract_checkpoint_tarball_handles_flat_tarball(tmp_path) -> None:
    source_dir = _write_checkpoint_tree(tmp_path / "source")
    tarball = tmp_path / "model.tar.gz"
    output_dir = tmp_path / "output"

    with tarfile.open(tarball, "w:gz") as tar:
        for path in sorted(source_dir.iterdir()):
            tar.add(path, arcname=path.name)

    restored = extract_checkpoint_tarball(tarball, output_dir)

    assert restored == output_dir.resolve()
    assert (output_dir / "config.json").exists()
    assert (output_dir / "tokenizer.json").exists()
    assert (output_dir / "model.safetensors").exists()
