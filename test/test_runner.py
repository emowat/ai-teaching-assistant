from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser
from rag_eng.config import Settings
from rag_eng.run_schemas import RunResult

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_CPP = REPO_ROOT / "runner" / "run_cpp.py"


def _has_gpp() -> bool:
    return shutil.which("g++") is not None


@pytest.mark.skipif(not _has_gpp(), reason="g++ not installed")
def test_execute_cpp_job_compiles_valid_program(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_cpp", RUN_CPP)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    workspace = tmp_path / "workspace"
    result = module.execute_cpp_job(
        {
            "files": {
                "main.cpp": '#include <iostream>\nint main(){ std::cout << "ok"; }\n',
            },
            "entrypoint": "main.cpp",
            "mode": "compile",
        },
        workspace,
    )

    assert result["compile"]["success"] is True


@pytest.mark.skipif(not _has_gpp(), reason="g++ not installed")
def test_execute_cpp_job_reports_compile_errors(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_cpp", RUN_CPP)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    workspace = tmp_path / "workspace"
    result = module.execute_cpp_job(
        {
            "files": {"main.cpp": "int main() { return 0\n"},
            "entrypoint": "main.cpp",
            "mode": "compile",
        },
        workspace,
    )

    assert result["compile"]["success"] is False
    assert result["summary"]["compile_failed"] is True


def test_run_cpp_job_subprocess_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_eng.runner_client import run_cpp_job

    if not _has_gpp():
        pytest.skip("g++ not installed")

    settings = Settings(
        qdrant_url=None,
        qdrant_api_key=None,
        qdrant_collection_name="test",
        qdrant_guidelines_collection_name="test",
        cohere_api_key=None,
        embedding_model="test",
        app_host="0.0.0.0",
        app_port=8001,
        gradio_port=7860,
        admin_token=None,
        log_level="INFO",
        raw_data_path=str(REPO_ROOT / "raw_data"),
        cognito_region=None,
        cognito_user_pool_id=None,
        cognito_app_client_id=None,
        cognito_issuer=None,
        cognito_jwks_url=None,
        runner_mode="subprocess",
        runner_image="codingrabbit-cpp-runner:0.1",
        cors_origins=("http://localhost:5173",),
    )

    result = run_cpp_job(
        {
            "files": {
                "main.cpp": '#include <iostream>\nint main(){ return 0; }\n',
            },
            "entrypoint": "main.cpp",
            "mode": "compile",
        },
        settings=settings,
    )

    assert isinstance(result, RunResult)
    assert result.compile.success is True


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_compile_endpoint_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/run/compile",
        json={"files": {"main.cpp": "int main(){return 0;}"}},
    )
    assert response.status_code == 401


def test_compile_endpoint_returns_result(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    def _student(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="student-sub",
            email="student@test.codingrabbit.dev",
            username="student@test.codingrabbit.dev",
            groups=["Students"],
            primary_role="student",
        )

    def _fake_run(payload, settings=None):
        return RunResult.model_validate(
            {
                "compile": {
                    "success": False,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "error: expected ';'",
                    "duration_ms": 10,
                    "timed_out": False,
                },
                "run": None,
                "tests": [],
                "summary": {"compile_failed": True, "passed": 0, "failed": 0},
            }
        )

    monkeypatch.setattr("rag_eng.auth.dependencies.verify_cognito_access_token", _student)
    monkeypatch.setattr("rag_eng.api.run_cpp_job", _fake_run)

    response = client.post(
        "/run/compile",
        headers={"Authorization": "Bearer valid-token"},
        json={"files": {"main.cpp": "int main(){return 0}"}, "entrypoint": "main.cpp"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["result"]["compile"]["stderr"]
