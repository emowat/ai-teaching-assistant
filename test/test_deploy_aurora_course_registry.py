from __future__ import annotations

from deploy.deploy_aurora_course_registry import (
    DEFAULT_SQL_FILE,
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

    assert len(statements) == 4
    assert statements[0].startswith("CREATE TABLE IF NOT EXISTS courses")
    assert statements[1].startswith("CREATE TABLE IF NOT EXISTS course_aliases")
    assert statements[2].startswith("INSERT INTO courses")
    assert statements[3].startswith("INSERT INTO course_aliases")
