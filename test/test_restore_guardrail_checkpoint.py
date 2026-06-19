from __future__ import annotations

import tarfile
from pathlib import Path

from deploy.restore_guardrail_checkpoint import (
    extract_checkpoint_tarball,
    parse_s3_uri,
)


def _write_checkpoint_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text('{"architectures": ["RobertaForSequenceClassification"]}')
    (root / "tokenizer.json").write_text('{"version": "1.0"}')
    (root / "model.safetensors").write_text("weights")
    return root


def _build_tarball(source: Path, tarball_path: Path, *, arcname: str | None = None) -> Path:
    with tarfile.open(tarball_path, "w:gz") as tar:
        if arcname is None:
            for child in sorted(source.iterdir()):
                tar.add(child, arcname=child.name)
        else:
            tar.add(source, arcname=arcname)
    return tarball_path


def test_parse_s3_uri():
    bucket, key = parse_s3_uri("s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz")
    assert bucket == "codingrabbit-data-dev"
    assert key == "models/guardrails/codebert_v2_1/model.tar.gz"


def test_extract_checkpoint_tarball_handles_flat_tarball(tmp_path):
    source = _write_checkpoint_tree(tmp_path / "flat")
    tarball = _build_tarball(source, tmp_path / "flat.tar.gz")
    output_dir = tmp_path / "output"

    restored = extract_checkpoint_tarball(tarball, output_dir)

    assert restored == output_dir.resolve()
    assert (output_dir / "config.json").exists()
    assert (output_dir / "tokenizer.json").exists()
    assert (output_dir / "model.safetensors").exists()


def test_extract_checkpoint_tarball_flattens_nested_directory(tmp_path):
    bundle = _write_checkpoint_tree(tmp_path / "nested" / "bundle")
    tarball = _build_tarball(bundle, tmp_path / "nested.tar.gz", arcname="bundle")
    output_dir = tmp_path / "output"

    restored = extract_checkpoint_tarball(tarball, output_dir)

    assert restored == output_dir.resolve()
    assert (output_dir / "config.json").exists()
    assert (output_dir / "tokenizer.json").exists()
    assert (output_dir / "model.safetensors").exists()
