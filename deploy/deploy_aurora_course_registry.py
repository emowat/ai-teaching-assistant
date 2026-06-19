"""Bootstrap the Aurora-backed course registry for the capstone.

This module executes the versioned SQL in `deploy/sql/aurora_course_registry.sql`
through the Aurora Data API, then verifies that the expected course rows exist.
It is intentionally small and operational so the schema can live in Git while the
deployment step stays reproducible.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import boto3


DEFAULT_SQL_FILE = Path(__file__).resolve().parent / "sql" / "aurora_course_registry.sql"


def _build_client(region: str, profile: str | None):
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("rds-data")


def split_sql_statements(sql_text: str) -> list[str]:
    """Split a simple SQL file into executable statements.

    The bootstrap SQL is intentionally simple:
    - line comments are allowed
    - statements terminate with ';'
    - block comments are not used
    """
    statements: list[str] = []
    current: list[str] = []

    for raw_line in sql_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("--"):
            continue

        current.append(raw_line.rstrip())
        if stripped.endswith(";"):
            statement = "\n".join(current).strip()
            if statement.endswith(";"):
                statement = statement[:-1].strip()
            if statement:
                statements.append(statement)
            current = []

    if any(line.strip() for line in current):
        raise ValueError("SQL file ended with an unterminated statement.")

    return statements


def load_sql_statements(sql_file: Path) -> list[str]:
    """Load and split the schema SQL file."""
    if not sql_file.is_file():
        raise FileNotFoundError(f"SQL file not found: {sql_file}")
    return split_sql_statements(sql_file.read_text(encoding="utf-8"))


def _execute_statement(
    client,
    *,
    resource_arn: str,
    secret_arn: str,
    database: str,
    statement: str,
    transaction_id: str | None = None,
) -> None:
    kwargs = {
        "resourceArn": resource_arn,
        "secretArn": secret_arn,
        "database": database,
        "sql": statement,
    }
    if transaction_id is not None:
        kwargs["transactionId"] = transaction_id
    client.execute_statement(**kwargs)


def apply_schema(
    *,
    client,
    resource_arn: str,
    secret_arn: str,
    database: str,
    sql_file: Path,
) -> None:
    """Apply the registry schema and seed rows in a single transaction."""
    statements = load_sql_statements(sql_file)
    if not statements:
        raise ValueError(f"No SQL statements found in {sql_file}")

    transaction_id = client.begin_transaction(
        resourceArn=resource_arn,
        secretArn=secret_arn,
        database=database,
    )["transactionId"]
    try:
        for statement in statements:
            _execute_statement(
                client,
                resource_arn=resource_arn,
                secret_arn=secret_arn,
                database=database,
                statement=statement,
                transaction_id=transaction_id,
            )
        client.commit_transaction(transactionId=transaction_id)
    except Exception:
        try:
            client.rollback_transaction(transactionId=transaction_id)
        except Exception:
            pass
        raise


def _extract_scalar(field: dict[str, object]) -> object:
    if not field:
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "isNull"):
        if key in field:
            value = field[key]
            if key == "isNull":
                return None
            return value
    return next(iter(field.values()))


def _format_records(records: list[list[dict[str, object]]]) -> list[list[object]]:
    return [[_extract_scalar(field) for field in record] for record in records]


def verify_schema(
    *,
    client,
    resource_arn: str,
    secret_arn: str,
    database: str,
) -> None:
    """Print the active registry rows so the operator can confirm the seed."""
    for label, sql in (
        (
            "courses",
            "SELECT course_id, course_source, collection_name, display_name, is_active FROM courses ORDER BY course_id;",
        ),
        (
            "course_aliases",
            "SELECT alias, course_id, is_active FROM course_aliases ORDER BY alias;",
        ),
    ):
        response = client.execute_statement(
            resourceArn=resource_arn,
            secretArn=secret_arn,
            database=database,
            sql=sql,
        )
        rows = _format_records(response.get("records", []))
        print(f"{label}: {len(rows)} row(s)")
        for row in rows:
            print(f"  {row}")


def _resolve_env_default(name: str, fallback: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    return raw


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap the Aurora PostgreSQL course registry.",
    )
    parser.add_argument(
        "action",
        choices=("apply", "verify"),
        help="apply the SQL bootstrap or verify the current rows",
    )
    parser.add_argument(
        "--resource-arn",
        default=_resolve_env_default("AURORA_COURSE_REGISTRY_RESOURCE_ARN"),
        help="Aurora cluster resource ARN (or set AURORA_COURSE_REGISTRY_RESOURCE_ARN)",
    )
    parser.add_argument(
        "--secret-arn",
        default=_resolve_env_default("AURORA_COURSE_REGISTRY_SECRET_ARN"),
        help="Secrets Manager ARN for the DB credentials (or set AURORA_COURSE_REGISTRY_SECRET_ARN)",
    )
    parser.add_argument(
        "--database",
        default=_resolve_env_default("AURORA_COURSE_REGISTRY_DATABASE", "postgres"),
        help="Database name inside the Aurora cluster (default: postgres)",
    )
    parser.add_argument(
        "--region",
        default=_resolve_env_default("AWS_REGION", "us-east-1"),
        help="AWS region for the Data API client (default: AWS_REGION or us-east-1)",
    )
    parser.add_argument(
        "--profile",
        default=_resolve_env_default("AWS_PROFILE"),
        help="Optional AWS profile for boto3 session",
    )
    parser.add_argument(
        "--sql-file",
        default=Path(
            _resolve_env_default(
                "AURORA_COURSE_REGISTRY_SQL_FILE",
                str(DEFAULT_SQL_FILE),
            )
        ),
        type=Path,
        help="Path to the registry SQL file (default: deploy/sql/aurora_course_registry.sql)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the statements that would be executed and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.resource_arn:
        parser.error("--resource-arn or AURORA_COURSE_REGISTRY_RESOURCE_ARN is required")
    if not args.secret_arn:
        parser.error("--secret-arn or AURORA_COURSE_REGISTRY_SECRET_ARN is required")

    statements = load_sql_statements(args.sql_file)
    if args.dry_run:
        print(f"{args.sql_file}: {len(statements)} statement(s)")
        for idx, statement in enumerate(statements, start=1):
            print(f"--- statement {idx} ---")
            print(statement)
        return 0

    client = _build_client(args.region, args.profile)

    if args.action == "apply":
        print(f"Applying {len(statements)} SQL statement(s) from {args.sql_file}")
        apply_schema(
            client=client,
            resource_arn=args.resource_arn,
            secret_arn=args.secret_arn,
            database=args.database,
            sql_file=args.sql_file,
        )
        print("Schema applied successfully.")

    verify_schema(
        client=client,
        resource_arn=args.resource_arn,
        secret_arn=args.secret_arn,
        database=args.database,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
