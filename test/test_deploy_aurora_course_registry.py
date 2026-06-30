from __future__ import annotations

from deploy.deploy_aurora_course_registry import (
    DEFAULT_SQL_FILE,
    apply_schema,
    load_sql_statements,
    split_sql_statements,
)


def test_split_sql_statements_ignores_comments_and_blank_lines() -> None:
    sql = """
    -- comment

    CREATE TABLE foo (
      id text primary key
    );

    -- another comment
    INSERT INTO foo (id)
    VALUES ('a');
    """

    statements = split_sql_statements(sql)

    assert statements == [
        "CREATE TABLE foo (\n      id text primary key\n    )",
        "INSERT INTO foo (id)\n    VALUES ('a')",
    ]


def test_load_sql_statements_reads_repo_bootstrap_file() -> None:
    statements = load_sql_statements(DEFAULT_SQL_FILE)

    assert len(statements) == 19
    assert statements[0].startswith("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    assert statements[1].startswith("CREATE TABLE IF NOT EXISTS courses")
    assert statements[2].startswith("CREATE TABLE IF NOT EXISTS course_aliases")
    assert statements[3].startswith(
        "CREATE TABLE IF NOT EXISTS course_corpus_versions"
    )
    assert statements[4].startswith("CREATE TABLE IF NOT EXISTS users")
    assert statements[5].startswith("CREATE TABLE IF NOT EXISTS sections")
    assert statements[6].startswith(
        "CREATE TABLE IF NOT EXISTS section_memberships"
    )
    assert statements[7].startswith("CREATE INDEX IF NOT EXISTS users_email_idx")
    assert statements[8].startswith("CREATE INDEX IF NOT EXISTS users_cognito_sub_idx")
    assert statements[9].startswith(
        "CREATE INDEX IF NOT EXISTS sections_course_id_is_active_idx"
    )
    assert statements[10].startswith(
        "CREATE INDEX IF NOT EXISTS section_memberships_user_id_status_idx"
    )
    assert statements[11].startswith(
        "CREATE INDEX IF NOT EXISTS section_memberships_section_id_role_status_idx"
    )
    assert statements[12].startswith("CREATE TABLE IF NOT EXISTS ingestion_jobs")
    assert statements[13].startswith("CREATE TABLE IF NOT EXISTS tutor_sessions")
    assert statements[14].startswith("CREATE TABLE IF NOT EXISTS tutor_turns")
    assert statements[15].startswith(
        "CREATE TABLE IF NOT EXISTS tutor_turn_snapshots"
    )
    assert statements[16].startswith("CREATE TABLE IF NOT EXISTS telemetry_events")
    assert statements[17].startswith("INSERT INTO courses")
    assert statements[18].startswith("INSERT INTO course_aliases")
    assert "'course_knowledge'" in statements[17]
    assert "'mit14_course_BAAI_bge_large_en_v1_5'" in statements[17]
    assert "'harvard_cs50_BAAI_bge_large_en_v1_5'" in statements[17]


class _ApplySchemaClient:
    def __init__(self):
        self.begin_kwargs = None
        self.execute_kwargs = []
        self.commit_kwargs = None
        self.rollback_kwargs = None

    def begin_transaction(self, **kwargs):
        self.begin_kwargs = kwargs
        return {"transactionId": "txn-123"}

    def execute_statement(self, **kwargs):
        self.execute_kwargs.append(kwargs)
        return {}

    def commit_transaction(self, **kwargs):
        self.commit_kwargs = kwargs

    def rollback_transaction(self, **kwargs):
        self.rollback_kwargs = kwargs


def test_apply_schema_commits_with_required_data_api_arns(tmp_path) -> None:
    sql_file = tmp_path / "schema.sql"
    sql_file.write_text(
        """
        CREATE TABLE foo (
          id text primary key
        );
        INSERT INTO foo (id) VALUES ('a');
        """
    )
    client = _ApplySchemaClient()

    apply_schema(
        client=client,
        resource_arn="arn:aws:rds:us-east-1:123:cluster:test",
        secret_arn="arn:aws:secretsmanager:us-east-1:123:secret:test",
        database="postgres",
        sql_file=sql_file,
    )

    assert client.begin_kwargs == {
        "resourceArn": "arn:aws:rds:us-east-1:123:cluster:test",
        "secretArn": "arn:aws:secretsmanager:us-east-1:123:secret:test",
        "database": "postgres",
    }
    assert client.commit_kwargs == {
        "resourceArn": "arn:aws:rds:us-east-1:123:cluster:test",
        "secretArn": "arn:aws:secretsmanager:us-east-1:123:secret:test",
        "transactionId": "txn-123",
    }
    assert client.rollback_kwargs is None
    assert len(client.execute_kwargs) == 2
