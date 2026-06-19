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

    assert len(statements) == 7
    assert statements[0].startswith("CREATE TABLE IF NOT EXISTS courses")
    assert statements[1].startswith("CREATE TABLE IF NOT EXISTS course_aliases")
    assert statements[2].startswith("CREATE TABLE IF NOT EXISTS tutor_sessions")
    assert statements[3].startswith("CREATE TABLE IF NOT EXISTS tutor_turns")
    assert statements[4].startswith("CREATE TABLE IF NOT EXISTS telemetry_events")
    assert statements[5].startswith("INSERT INTO courses")
    assert statements[6].startswith("INSERT INTO course_aliases")
    assert "'course_knowledge'" in statements[5]
    assert "'harvard_cs50'" in statements[5]


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
