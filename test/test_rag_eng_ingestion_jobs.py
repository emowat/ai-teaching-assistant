from __future__ import annotations

from datetime import datetime, timezone

from rag_eng.ingestion_jobs import (
    IngestionRuntimeConfig,
    build_ingestion_worker_command,
    complete_ingestion_job,
    launch_ingestion_job,
)
from rag_eng.schemas import IngestionJobLaunchRequest


def _runtime() -> IngestionRuntimeConfig:
    return IngestionRuntimeConfig(
        database_url="postgresql://example",
        ecs_cluster="cluster",
        ecs_task_definition="taskdef",
        ecs_container_name="worker",
        ecs_launch_type="FARGATE",
        ecs_platform_version="LATEST",
        ecs_assign_public_ip="ENABLED",
        ecs_subnet_ids=("subnet-a", "subnet-b"),
        ecs_security_group_ids=("sg-a",),
        aws_region="us-east-1",
        aws_profile=None,
        connect_timeout_seconds=5,
    )


def _parse_request() -> IngestionJobLaunchRequest:
    return IngestionJobLaunchRequest(
        course_id="mit14",
        job_kind="parse",
        bucket="codingrabbit-data-dev",
        input_prefix="teacher_uploads/mit14",
        output_prefix="parsed_json/mit14",
    )


def _chunk_request() -> IngestionJobLaunchRequest:
    return IngestionJobLaunchRequest(
        course_id="mit14",
        job_kind="chunk-index",
        bucket="codingrabbit-data-dev",
        input_prefix="parsed_json/mit14",
        prepared_output_prefix="prepared_chunks/mit14",
        recreate_collection=True,
    )


def test_build_ingestion_worker_command_matches_job_kind() -> None:
    parse_command = build_ingestion_worker_command(
        _parse_request(),
        course_id="mit14",
        collection_name="course_knowledge",
    )
    chunk_command = build_ingestion_worker_command(
        _chunk_request(),
        course_id="mit14",
        collection_name="course_knowledge",
    )

    assert parse_command[:4] == [
        "python",
        "-m",
        "data_ingestion.ingestion_worker",
        "parse",
    ]
    assert "--output-prefix" in parse_command
    assert "--collection-name" not in parse_command

    assert chunk_command[:4] == [
        "python",
        "-m",
        "data_ingestion.ingestion_worker",
        "chunk-index",
    ]
    assert "--collection-name" in chunk_command
    assert "--prepared-output-prefix" in chunk_command
    assert "--recreate-collection" in chunk_command


class _FakeStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self.versions: dict[str, dict[str, object]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


class _FakeCursor:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store
        self.fetchone_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        statement = " ".join(sql.split()).upper()
        params = params or ()

        if statement.startswith("INSERT INTO COURSE_CORPUS_VERSIONS"):
            (
                version_id,
                course_id,
                collection_name,
                source_bucket,
                source_prefix,
                parsed_prefix,
                prepared_prefix,
                recreate_collection,
                metadata,
            ) = params
            self.store.versions[str(version_id)] = {
                "course_corpus_version_id": str(version_id),
                "course_id": str(course_id),
                "collection_name": str(collection_name),
                "source_bucket": str(source_bucket),
                "source_prefix": str(source_prefix),
                "parsed_prefix": parsed_prefix,
                "prepared_prefix": prepared_prefix,
                "status": "queued",
                "active": False,
                "recreate_collection": bool(recreate_collection),
                "metadata": metadata,
                "created_at": self.store._now(),
                "updated_at": self.store._now(),
                "started_at": None,
                "completed_at": None,
            }
            return {}

        if statement.startswith("INSERT INTO INGESTION_JOBS"):
            (
                job_id,
                course_id,
                course_corpus_version_id,
                job_kind,
                bucket,
                input_prefix,
                output_prefix,
                prepared_output_prefix,
                collection_name,
                recreate_collection,
                ecs_cluster,
                ecs_task_definition,
                ecs_container_name,
                request_payload,
            ) = params
            self.store.jobs[str(job_id)] = {
                "job_id": str(job_id),
                "course_id": str(course_id),
                "course_corpus_version_id": (
                    str(course_corpus_version_id)
                    if course_corpus_version_id is not None
                    else None
                ),
                "job_kind": str(job_kind),
                "status": "queued",
                "message": "",
                "ecs_cluster": str(ecs_cluster),
                "ecs_task_definition": str(ecs_task_definition),
                "ecs_container_name": str(ecs_container_name),
                "ecs_task_arn": None,
                "collection_name": str(collection_name),
                "bucket": str(bucket),
                "input_prefix": str(input_prefix),
                "output_prefix": output_prefix,
                "prepared_output_prefix": prepared_output_prefix,
                "recreate_collection": bool(recreate_collection),
                "request_payload": request_payload,
                "ecs_response": {},
                "created_at": self.store._now(),
                "updated_at": self.store._now(),
                "started_at": None,
                "completed_at": None,
            }
            return {}

        if statement.startswith("UPDATE INGESTION_JOBS"):
            (
                status,
                message,
                ecs_task_arn,
                ecs_response,
                started,
                completed,
                job_id,
            ) = params
            row = self.store.jobs[str(job_id)]
            row["status"] = str(status)
            row["message"] = str(message)
            if ecs_task_arn is not None:
                row["ecs_task_arn"] = str(ecs_task_arn)
            if ecs_response is not None:
                row["ecs_response"] = ecs_response
            row["updated_at"] = self.store._now()
            if started:
                row["started_at"] = row["started_at"] or self.store._now()
            if completed:
                row["completed_at"] = self.store._now()
            return {}

        if statement.startswith("UPDATE COURSE_CORPUS_VERSIONS"):
            (
                status,
                active,
                metadata,
                started,
                completed,
                version_id,
            ) = params
            row = self.store.versions[str(version_id)]
            row["status"] = str(status)
            row["active"] = bool(active)
            if metadata is not None:
                row["metadata"] = metadata
            row["updated_at"] = self.store._now()
            if started:
                row["started_at"] = row["started_at"] or self.store._now()
            if completed:
                row["completed_at"] = self.store._now()
            return {}

        if statement.startswith("SELECT"):
            job_id = str(params[0])
            row = self.store.jobs[job_id]
            self.fetchone_result = (
                row["job_id"],
                row["course_id"],
                row["course_corpus_version_id"],
                row["job_kind"],
                row["status"],
                row["message"],
                row["ecs_cluster"],
                row["ecs_task_definition"],
                row["ecs_container_name"],
                row["ecs_task_arn"],
                row["collection_name"],
                row["bucket"],
                row["input_prefix"],
                row["output_prefix"],
                row["prepared_output_prefix"],
                row["recreate_collection"],
                row["request_payload"],
                row["ecs_response"],
                row["created_at"],
                row["updated_at"],
                row["started_at"],
                row["completed_at"],
            )
            return {}

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.fetchone_result


class _FakeConnection:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor(self.store)


class _FakeEcsClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def run_task(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_launch_ingestion_job_registers_chunk_index_and_runs_ecs(monkeypatch) -> None:
    store = _FakeStore()
    fake_ecs = _FakeEcsClient(
        {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}
    )
    runtime = _runtime()

    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._resolve_course",
        lambda course_id, collection_name: ("mit14", "course_knowledge"),
    )
    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._connect_postgres",
        lambda *args, **kwargs: _FakeConnection(store),
    )
    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._json_adapter",
        lambda data: data,
    )

    response = launch_ingestion_job(
        _chunk_request(),
        runtime=runtime,
        ecs_client=fake_ecs,
    )

    assert response.status == "running"
    assert response.registered is True
    assert response.course_corpus_version_id == response.job_id
    assert response.ecs_task_arn == "arn:aws:ecs:task/123"
    assert store.jobs[response.job_id]["status"] == "running"
    assert store.versions[response.course_corpus_version_id]["status"] == "running"
    assert store.versions[response.course_corpus_version_id]["active"] is False
    assert fake_ecs.calls[0]["cluster"] == "cluster"
    overrides = fake_ecs.calls[0]["overrides"]["containerOverrides"][0]
    assert overrides["name"] == "worker"
    assert "--collection-name" in overrides["command"]
    assert "course_knowledge" in overrides["command"]
    assert "--prepared-output-prefix" in overrides["command"]
    assert "--recreate-collection" in overrides["command"]
    environment = {item["name"]: item["value"] for item in overrides["environment"]}
    assert environment["INGESTION_JOB_ID"] == response.job_id
    assert environment["COURSE_CORPUS_VERSION_ID"] == response.course_corpus_version_id

    completed = complete_ingestion_job(
        response.job_id,
        status="completed",
        message="Indexed successfully.",
        ecs_response={"chunks_indexed": 4},
        runtime=runtime,
    )

    assert completed is True
    assert store.jobs[response.job_id]["status"] == "completed"
    assert store.jobs[response.job_id]["completed_at"] is not None
    assert store.versions[response.course_corpus_version_id]["status"] == "completed"
    assert store.versions[response.course_corpus_version_id]["active"] is True


def test_launch_ingestion_job_parse_omits_corpus_version(monkeypatch) -> None:
    store = _FakeStore()
    fake_ecs = _FakeEcsClient(
        {"tasks": [{"taskArn": "arn:aws:ecs:task/124"}], "failures": []}
    )
    runtime = _runtime()

    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._resolve_course",
        lambda course_id, collection_name: ("mit14", "course_knowledge"),
    )
    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._connect_postgres",
        lambda *args, **kwargs: _FakeConnection(store),
    )
    monkeypatch.setattr(
        "rag_eng.ingestion_jobs._json_adapter",
        lambda data: data,
    )

    response = launch_ingestion_job(
        _parse_request(),
        runtime=runtime,
        ecs_client=fake_ecs,
    )

    assert response.status == "running"
    assert response.course_corpus_version_id is None
    assert store.versions == {}
    overrides = fake_ecs.calls[0]["overrides"]["containerOverrides"][0]
    assert "--collection-name" not in overrides["command"]
    assert "--output-prefix" in overrides["command"]
    assert overrides["command"][3] == "parse"
