"""
Download the fine-tuned Qwen model from Google Drive and upload to S3.

The model must be in standard HuggingFace format (config.json, tokenizer files,
model weights as .safetensors or .bin shards).  This script packages everything
into a model.tar.gz and uploads to the S3 path that deploy_sagemaker.py expects.

Usage:
    # Download from Drive and upload to S3 (full flow):
    python deploy/upload_model.py upload

    # Only download (inspect before uploading):
    python deploy/upload_model.py download

    # Only package an existing local download:
    python deploy/upload_model.py package --local-dir ./model_download

    # Only upload an existing tar.gz:
    python deploy/upload_model.py push --tar ./model.tar.gz

Prerequisites:
    pip install gdown boto3

    The Google Drive folder must be shared with "Anyone with the link" OR
    you must be logged in with gdown credentials:
        gdown auth   (opens browser)

Google Drive folder:
    https://drive.google.com/drive/u/0/folders/14Gp0dkdI3RJi7AqH_uADkzF69ou3Ev3O
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
from pathlib import Path

import boto3

try:
    import gdown
except ImportError:
    gdown = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration — override with CLI flags or environment variables
# ---------------------------------------------------------------------------

DRIVE_FOLDER_ID = "14Gp0dkdI3RJi7AqH_uADkzF69ou3Ev3O"

DEFAULT_DOWNLOAD_DIR = Path("./model_download")
DEFAULT_TAR_PATH = Path("./model.tar.gz")

S3_BUCKET = os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
S3_MODEL_KEY = "models/qwen-finetuned/model.tar.gz"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE") or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_gdown() -> None:
    if gdown is None:
        print("ERROR: gdown is not installed.  Run:  pip install gdown")
        sys.exit(1)


def download(output_dir: Path) -> None:
    """Download the Drive folder to a local directory."""
    _require_gdown()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Google Drive folder {DRIVE_FOLDER_ID} → {output_dir}")
    print("(This may take several minutes for a 14B model.)\n")
    gdown.download_folder(
        id=DRIVE_FOLDER_ID,
        output=str(output_dir),
        quiet=False,
        use_cookies=False,
    )
    files = list(output_dir.rglob("*"))
    print(f"\nDownloaded {len(files)} files to {output_dir}")


def package(local_dir: Path, tar_path: Path) -> None:
    """Package a local HuggingFace model directory into model.tar.gz.

    SageMaker extracts model.tar.gz to /opt/ml/model/.  All files must be at
    the top level inside the archive (no extra subdirectory).
    """
    model_files = list(local_dir.rglob("*"))
    if not model_files:
        print(f"ERROR: No files found in {local_dir}")
        sys.exit(1)

    # Warn if required HF files are missing
    required = {"config.json", "tokenizer_config.json"}
    found_names = {f.name for f in model_files}
    missing = required - found_names
    if missing:
        print(f"WARNING: Potentially missing HuggingFace files: {missing}")
        print("  Continuing anyway — verify the model directory is complete.")

    print(f"Packaging {len(model_files)} files → {tar_path}")
    with tarfile.open(tar_path, "w:gz") as tar:
        for file_path in model_files:
            if file_path.is_file():
                # Store relative to local_dir so files land at top level in /opt/ml/model/
                arcname = file_path.relative_to(local_dir)
                tar.add(file_path, arcname=str(arcname))

    size_mb = tar_path.stat().st_size / (1024 ** 2)
    print(f"Packaged: {tar_path}  ({size_mb:.0f} MB)")


def push(tar_path: Path, bucket: str, key: str, region: str, profile: str | None) -> None:
    """Upload model.tar.gz to S3."""
    if not tar_path.exists():
        print(f"ERROR: {tar_path} does not exist.  Run the 'package' step first.")
        sys.exit(1)

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")

    size_mb = tar_path.stat().st_size / (1024 ** 2)
    s3_uri = f"s3://{bucket}/{key}"
    print(f"Uploading {tar_path} ({size_mb:.0f} MB) → {s3_uri}")
    print("(Large model uploads may take several minutes.)\n")

    s3.upload_file(
        str(tar_path),
        bucket,
        key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
        Callback=_UploadProgress(tar_path.stat().st_size),
    )
    print(f"\nUpload complete: {s3_uri}")
    print(f"Set MODEL_DATA_URI={s3_uri} before running deploy_sagemaker.py")


class _UploadProgress:
    """Simple progress callback for boto3 upload_file."""

    def __init__(self, total_bytes: int) -> None:
        self._total = total_bytes
        self._uploaded = 0

    def __call__(self, bytes_transferred: int) -> None:
        self._uploaded += bytes_transferred
        pct = self._uploaded / self._total * 100
        print(f"\r  {pct:.1f}%  ({self._uploaded / 1024**2:.0f} / {self._total / 1024**2:.0f} MB)", end="", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Qwen fine-tune from Google Drive and upload to S3"
    )
    parser.add_argument(
        "action",
        choices=["download", "package", "push", "upload"],
        help=(
            "download — fetch from Drive; "
            "package — tar.gz local dir; "
            "push — S3 upload; "
            "upload — all three steps"
        ),
    )
    parser.add_argument("--local-dir", default=str(DEFAULT_DOWNLOAD_DIR), help="Local model directory")
    parser.add_argument("--tar", default=str(DEFAULT_TAR_PATH), help="Path for model.tar.gz")
    parser.add_argument("--bucket", default=S3_BUCKET, help="S3 bucket name")
    parser.add_argument("--key", default=S3_MODEL_KEY, help="S3 object key for model.tar.gz")
    parser.add_argument("--region", default=AWS_REGION)
    parser.add_argument("--profile", default=AWS_PROFILE)
    args = parser.parse_args()

    local_dir = Path(args.local_dir)
    tar_path = Path(args.tar)

    if args.action in ("download", "upload"):
        download(local_dir)

    if args.action in ("package", "upload"):
        package(local_dir, tar_path)

    if args.action in ("push", "upload"):
        push(tar_path, args.bucket, args.key, args.region, args.profile)


if __name__ == "__main__":
    main()
