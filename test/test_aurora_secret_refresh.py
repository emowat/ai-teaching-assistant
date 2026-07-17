from __future__ import annotations

import rag_eng.aurora_secret_refresh as aurora_secret_refresh
from rag_eng.aurora_secret_refresh import (
    get_cached_refreshed_url,
    is_password_auth_error,
    refresh_database_url_from_secrets_manager,
)


def test_is_password_auth_error_matches_sqlstate() -> None:
    class _FakeError(Exception):
        sqlstate = "28P01"

    assert is_password_auth_error(_FakeError("anything")) is True


def test_is_password_auth_error_matches_message_text() -> None:
    error = RuntimeError(
        'connection failed: connection to server at "10.0.0.1" FATAL:  '
        'password authentication failed for user "cr_app"'
    )
    assert is_password_auth_error(error) is True


def test_is_password_auth_error_false_for_unrelated_errors() -> None:
    assert is_password_auth_error(RuntimeError("connection timeout expired")) is False


def test_refresh_returns_none_without_secret_id_configured(monkeypatch) -> None:
    monkeypatch.delenv("COURSE_REGISTRY_DATABASE_URL_SECRET_ID", raising=False)
    aurora_secret_refresh._refreshed_database_url = None

    assert refresh_database_url_from_secrets_manager() is None
    assert get_cached_refreshed_url() is None


def test_refresh_fetches_and_caches_new_value(monkeypatch) -> None:
    monkeypatch.setenv(
        "COURSE_REGISTRY_DATABASE_URL_SECRET_ID",
        "arn:aws:secretsmanager:us-east-1:123:secret:codingrabbit/rag_eng/COURSE_REGISTRY_DATABASE_URL",
    )
    aurora_secret_refresh._refreshed_database_url = None

    class _FakeSecretsManagerClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_secret_value(self, *, SecretId: str):
            self.calls.append(SecretId)
            return {"SecretString": "postgresql://cr_app:fresh-password@aurora/db"}

    fake_client = _FakeSecretsManagerClient()

    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, region_name=None):
            assert service_name == "secretsmanager"
            return fake_client

    import sys

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)

    result = refresh_database_url_from_secrets_manager()

    assert result == "postgresql://cr_app:fresh-password@aurora/db"
    assert get_cached_refreshed_url() == "postgresql://cr_app:fresh-password@aurora/db"
    assert len(fake_client.calls) == 1


def test_refresh_builds_url_from_aws_managed_json_secret(monkeypatch) -> None:
    # This is the real shape of RDS's "Manage master user password" secret -
    # {"username": ..., "password": ...} only, no host/port/database.
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL_SECRET_ID", "rds!cluster-abc123")
    monkeypatch.setenv(
        "COURSE_REGISTRY_DB_HOST",
        "codingrabbit-course-registry-aurora.cluster-xyz.us-east-1.rds.amazonaws.com",
    )
    monkeypatch.setenv("COURSE_REGISTRY_DB_PORT", "5432")
    monkeypatch.setenv("COURSE_REGISTRY_DB_NAME", "postgres")
    monkeypatch.setenv("COURSE_REGISTRY_DB_SSLMODE", "require")
    aurora_secret_refresh._refreshed_database_url = None

    class _FakeClient:
        def get_secret_value(self, *, SecretId: str):
            assert SecretId == "rds!cluster-abc123"
            return {"SecretString": '{"username": "cr_app", "password": "p@ss/word=1"}'}

    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, region_name=None):
            return _FakeClient()

    import sys

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)

    result = refresh_database_url_from_secrets_manager()

    assert result == (
        "postgresql://cr_app:p%40ss%2Fword%3D1"
        "@codingrabbit-course-registry-aurora.cluster-xyz.us-east-1.rds.amazonaws.com"
        ":5432/postgres?sslmode=require"
    )
    assert get_cached_refreshed_url() == result


def test_refresh_json_secret_without_host_configured_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL_SECRET_ID", "rds!cluster-abc123")
    monkeypatch.delenv("COURSE_REGISTRY_DB_HOST", raising=False)
    aurora_secret_refresh._refreshed_database_url = None

    class _FakeClient:
        def get_secret_value(self, *, SecretId: str):
            return {"SecretString": '{"username": "cr_app", "password": "secret"}'}

    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, region_name=None):
            return _FakeClient()

    import sys

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)

    assert refresh_database_url_from_secrets_manager() is None
    assert get_cached_refreshed_url() is None


def test_refresh_returns_none_on_fetch_failure(monkeypatch) -> None:
    monkeypatch.setenv(
        "COURSE_REGISTRY_DATABASE_URL_SECRET_ID",
        "arn:aws:secretsmanager:us-east-1:123:secret:codingrabbit/rag_eng/COURSE_REGISTRY_DATABASE_URL",
    )
    aurora_secret_refresh._refreshed_database_url = None

    class _FailingClient:
        def get_secret_value(self, *, SecretId: str):
            raise RuntimeError("access denied")

    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, region_name=None):
            return _FailingClient()

    import sys

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)

    assert refresh_database_url_from_secrets_manager() is None
    assert get_cached_refreshed_url() is None
