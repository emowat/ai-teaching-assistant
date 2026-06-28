from __future__ import annotations

import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_eng.config import restore_runtime_config_from_s3  # noqa: E402


logger = logging.getLogger(__name__)


def main() -> int:
    try:
        restored = restore_runtime_config_from_s3()
    except Exception as exc:
        logger.warning("Runtime config restore skipped: %s", exc)
        return 0

    if restored:
        print("==> restored runtime config from S3")
    else:
        print("==> runtime config restore skipped (no S3 URI configured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
