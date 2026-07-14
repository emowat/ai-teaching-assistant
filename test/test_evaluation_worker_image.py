from __future__ import annotations

from pathlib import Path

from deploy.deployment_config import load_deploy_config
from deploy.evaluation_worker_image import (
    DEFAULT_REPOSITORY_NAME,
    _dockerfile_text,
    stage_build_context,
)


def test_deployment_config_points_to_dedicated_worker_image() -> None:
    config = load_deploy_config(Path("deploy/deployment.yaml"))

    assert config.evaluation_worker.image_uri is not None
    assert config.evaluation_worker.image_uri.endswith(
        "/codingrabbit-evaluation-worker:latest",
    )


def test_stage_build_context_copies_only_worker_sources(tmp_path: Path) -> None:
    build_root = stage_build_context(
        repo_root=Path(__file__).resolve().parent.parent,
        build_root=tmp_path / "worker-image",
    )

    assert (build_root / "Dockerfile").read_text(encoding="utf-8") == _dockerfile_text()
    assert (build_root / "requirements.txt").is_file()
    assert (build_root / "model_eval" / "evaluation_worker.py").is_file()
    assert (build_root / "model_eval" / "prompts.py").is_file()
    assert (build_root / "model_eval" / "requirements.txt").is_file()
    assert (build_root / "rag" / "__init__.py").is_file()
    assert (build_root / "rag" / "schemas.py").is_file()
    assert (build_root / "rag_eng" / "config.py").is_file()
    assert (build_root / "rag_eng" / "runtime_config.yaml").is_file()
    assert (build_root / "rag_eng" / "inference_config.yaml").is_file()
    assert not (build_root / "rag" / "loader.py").exists()
    assert not (build_root / "rag" / "pipeline.py").exists()
    assert not (build_root / "model_eval" / "evaluation").exists()
    assert not (build_root / "model_eval" / "Inputs").exists()
    assert not (build_root / "model_eval" / "test_data").exists()
    assert not (build_root / "model_eval" / "test_results").exists()
    assert DEFAULT_REPOSITORY_NAME == "codingrabbit-evaluation-worker"
