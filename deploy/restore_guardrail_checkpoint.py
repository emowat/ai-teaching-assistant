"""Restore the fine-tuned CodeBERT guardrail checkpoint from S3.

This helper downloads the `model.tar.gz` artifact, extracts it, and
normalizes the contents into a local Hugging Face checkpoint directory.
The runtime semantic guardrail loader reads from the same local target.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import boto3

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from output_guardrails.semantic_guardrail import resolve_checkpoint_dir  # noqa: E402

DEFAULT_S3_URI = "s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz"


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Split an S3 URI into bucket and key."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _safe_extract(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Extract a tarball while rejecting path traversal entries."""
    target_dir = target_dir.resolve()
    for member in tar.getmembers():
        member_path = (target_dir / member.name).resolve()
        if target_dir not in member_path.parents and member_path != target_dir:
            raise ValueError(f"Unsafe tar member path: {member.name}")
    tar.extractall(target_dir)


def _find_checkpoint_root(extract_root: Path) -> Path:
    """Locate the directory that contains the Hugging Face checkpoint."""
    extract_root = extract_root.resolve()
    if (extract_root / "config.json").exists():
        return extract_root

    child_dirs = [path for path in extract_root.iterdir() if path.is_dir()]
    if len(child_dirs) == 1 and (child_dirs[0] / "config.json").exists():
        return child_dirs[0]

    raise RuntimeError(
        f"Unable to locate a checkpoint root in {extract_root}. "
        "Expected config.json at the tarball root or in a single nested directory.",
    )


def extract_checkpoint_tarball(tarball_path: Path, output_dir: Path) -> Path:
    """Extract a tarball into a normalized checkpoint directory."""
    output_dir = output_dir.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="guardrail-checkpoint-") as temp_dir:
        temp_root = Path(temp_dir)
        extract_root = temp_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball_path, "r:gz") as tar:
            _safe_extract(tar, extract_root)
        checkpoint_root = _find_checkpoint_root(extract_root)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(checkpoint_root, output_dir)
    return output_dir


def restore_checkpoint_from_s3(
    s3_uri: str,
    output_dir: Path,
    *,
    profile: str | None = None,
    region: str | None = None,
) -> Path:
    """Download a checkpoint tarball from S3 and extract it locally."""
    bucket, key = parse_s3_uri(s3_uri)
    session_kwargs: dict[str, str] = {}
    if profile:
        session_kwargs["profile_name"] = profile
    if region:
        session_kwargs["region_name"] = region

    client = boto3.Session(**session_kwargs).client("s3")
    with tempfile.TemporaryDirectory(prefix="guardrail-checkpoint-") as temp_dir:
        tarball_path = Path(temp_dir) / "model.tar.gz"
        client.download_file(bucket, key, str(tarball_path))
        return extract_checkpoint_tarball(tarball_path, output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore the CodeBERT guardrail checkpoint from S3.")
    parser.add_argument(
        "--s3-uri",
        default=os.getenv("GUARDRAILS_CODEBERT_S3_URI", DEFAULT_S3_URI),
        help="S3 URI for model.tar.gz",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Local checkpoint directory (defaults to the guardrail runtime path)",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE"),
        help="AWS profile to use for the S3 download",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        help="AWS region to use for the S3 download",
    )
    args = parser.parse_args(argv)

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else resolve_checkpoint_dir()
    )

    print(f"Downloading guardrail checkpoint: {args.s3_uri}")
    print(f"Target checkpoint directory:    {output_dir}")
    if args.profile:
        print(f"AWS profile:                   {args.profile}")
    if args.region:
        print(f"AWS region:                    {args.region}")

    restored_dir = restore_checkpoint_from_s3(
        args.s3_uri,
        output_dir,
        profile=args.profile,
        region=args.region,
    )
    print(f"Checkpoint ready:              {restored_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
