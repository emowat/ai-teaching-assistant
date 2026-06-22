"""Restore the fine-tuned input CodeBERT guardrail checkpoint from S3.

Supports either:
  - a model.tar.gz artifact, or
  - a raw S3 prefix containing Hugging Face checkpoint files.
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

from input_guardrails.runtime import resolve_checkpoint_dir  # noqa: E402

DEFAULT_S3_URI = "s3://codingrabbit-data-dev/models/guardrails/input_codebert_v1/"


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Split an S3 URI into bucket and key/prefix."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _safe_extract(tar: tarfile.TarFile, target_dir: Path) -> None:
    target_dir = target_dir.resolve()
    for member in tar.getmembers():
        member_path = (target_dir / member.name).resolve()
        if target_dir not in member_path.parents and member_path != target_dir:
            raise ValueError(f"Unsafe tar member path: {member.name}")
    tar.extractall(target_dir)


def _find_checkpoint_root(extract_root: Path) -> Path:
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


def _find_tarball_file(search_root: Path) -> Path | None:
    """Find a tarball file within a downloaded S3 prefix, if one exists."""
    tarballs = [
        path
        for path in search_root.rglob("*")
        if path.is_file() and path.name.endswith((".tar.gz", ".tgz", ".tar"))
    ]
    if not tarballs:
        return None
    if len(tarballs) > 1:
        raise RuntimeError(
            f"Multiple checkpoint archives found under {search_root}: "
            f"{', '.join(str(path) for path in tarballs)}"
        )
    return tarballs[0]


def extract_checkpoint_tarball(tarball_path: Path, output_dir: Path) -> Path:
    """Extract a tarball into a normalized checkpoint directory."""
    output_dir = output_dir.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="input-guardrail-checkpoint-") as temp_dir:
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


def _sync_prefix_from_s3(
    client,
    bucket: str,
    prefix: str,
    output_dir: Path,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="input-guardrail-checkpoint-") as temp_dir:
        temp_root = Path(temp_dir) / "download"
        temp_root.mkdir(parents=True, exist_ok=True)
        paginator = client.get_paginator("list_objects_v2")
        found = False
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []) or []:
                key = item.get("Key", "")
                if not key or key.endswith("/"):
                    continue
                found = True
                relative = key[len(prefix):] if key.startswith(prefix) else key
                relative = relative.lstrip("/")
                destination = temp_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(bucket, key, str(destination))

        if not found:
            raise RuntimeError(f"No checkpoint files found under s3://{bucket}/{prefix}")

        output_dir = output_dir.expanduser().resolve()
        if output_dir.exists():
            shutil.rmtree(output_dir)
        checkpoint_root = None
        try:
            checkpoint_root = _find_checkpoint_root(temp_root)
        except RuntimeError:
            checkpoint_root = None
        if checkpoint_root is not None:
            shutil.copytree(checkpoint_root, output_dir)
            return output_dir

        tarball_path = _find_tarball_file(temp_root)
        if tarball_path is None:
            raise RuntimeError(
                f"No checkpoint root or archive found under s3://{bucket}/{prefix}"
            )
        return extract_checkpoint_tarball(tarball_path, output_dir)


def restore_checkpoint_from_s3(
    s3_uri: str,
    output_dir: Path,
    *,
    profile: str | None = None,
    region: str | None = None,
) -> Path:
    """Download a checkpoint tarball or prefix from S3 and restore it locally."""
    bucket, key = parse_s3_uri(s3_uri)
    session_kwargs: dict[str, str] = {}
    if profile:
        session_kwargs["profile_name"] = profile
    if region:
        session_kwargs["region_name"] = region

    client = boto3.Session(**session_kwargs).client("s3")
    if key.endswith((".tar.gz", ".tgz", ".tar")):
        with tempfile.TemporaryDirectory(prefix="input-guardrail-checkpoint-") as temp_dir:
            tarball_path = Path(temp_dir) / "model.tar.gz"
            client.download_file(bucket, key, str(tarball_path))
            return extract_checkpoint_tarball(tarball_path, output_dir)
    return _sync_prefix_from_s3(client, bucket, key, output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore the input CodeBERT guardrail checkpoint from S3.")
    parser.add_argument(
        "--s3-uri",
        default=os.getenv("INPUT_GUARDRAILS_CODEBERT_S3_URI", DEFAULT_S3_URI),
        help="S3 URI for the input guardrail checkpoint or model.tar.gz",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Local checkpoint directory (defaults to the input guardrail runtime path)",
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

    print(f"Downloading input guardrail checkpoint: {args.s3_uri}")
    print(f"Target checkpoint directory:          {output_dir}")
    if args.profile:
        print(f"AWS profile:                         {args.profile}")
    if args.region:
        print(f"AWS region:                          {args.region}")

    restored_dir = restore_checkpoint_from_s3(
        args.s3_uri,
        output_dir,
        profile=args.profile,
        region=args.region,
    )
    print(f"Checkpoint ready:                    {restored_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
