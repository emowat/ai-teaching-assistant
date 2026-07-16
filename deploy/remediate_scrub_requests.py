"""One-time remediation for scrub requests processed before scrub_user_data()
was fixed to actually delete data.

The old scrub_user_data() only redacted two JSON fields and cosmetically
renamed the `users` row — it never touched tutor_sessions/tutor_turns/
tutor_turn_snapshots/telemetry_events/ta_effectiveness_session_scores/
ta_effectiveness_turn_scores/reported_issues/section_memberships. Any
data_deletion_requests row already marked 'completed' was processed under
that old logic and needs to be re-run now that the fix is deployed.

Safe to re-run against the same user more than once: every statement inside
the fixed scrub_user_data() is a no-op if the rows are already gone.

Usage (from repo root):
    uv run deploy/remediate_scrub_requests.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_eng.app_registry import scrub_user_data  # noqa: E402
from rag_eng.aurora_retry import connect_postgres_with_retry  # noqa: E402

load_dotenv()

logger = logging.getLogger(__name__)


def _fetch_completed_deletion_user_ids(connection) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT user_id
            FROM data_deletion_requests
            WHERE status = 'completed'
            ORDER BY scrubbed_at ASC NULLS LAST
            """
        )
        rows = cursor.fetchall()
    return [str(row[0]) for row in rows]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-scrub every user whose deletion request was already marked "
            "completed, now that scrub_user_data() actually deletes data "
            "instead of just redacting a couple of fields."
        )
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected users without re-scrubbing them.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    env = os.environ

    database_url = (
        args.database_url
        or env.get("EVALUATION_DATABASE_URL")
        or env.get("COURSE_REGISTRY_DATABASE_URL")
        or env.get("DATABASE_URL")
    )
    if not database_url:
        parser.error(
            "A database URL is required (--database-url or COURSE_REGISTRY_DATABASE_URL)."
        )

    connection = connect_postgres_with_retry(database_url, profile="reliable")
    user_ids = _fetch_completed_deletion_user_ids(connection)
    connection.commit()
    logger.info("Found %d completed deletion request(s) to re-scrub.", len(user_ids))

    if args.dry_run:
        for user_id in user_ids:
            logger.info("[dry-run] Would re-scrub user %s", user_id)
        return 0

    for user_id in user_ids:
        scrub_user_data(user_id)
        logger.info("Re-scrubbed user %s", user_id)

    logger.info("Remediation complete: %d user(s) re-scrubbed.", len(user_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
