"""ECS ingestion worker for teacher uploads and parsed-envelopes indexing."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from data_ingestion import s3_teacher_file_parser as teacher_parser
from data_ingestion.chunking import (
    build_chunk_records_from_envelope,
    build_prepared_chunk_document,
    load_parsed_envelopes_from_dir,
    prepared_chunk_artifact_name,
)
from rag_eng.ingestion_jobs import complete_ingestion_job
from rag.runtime import create_qdrant_client, get_runtime_config


@dataclass(frozen=True)
class ChunkIndexSummary:
    """Summary returned by the chunk/index worker."""

    collection_name: str
    envelopes_processed: int
    chunks_indexed: int
    created_collection: bool
    prepared_artifacts_written: int


def _worker_job_id() -> str | None:
    job_id = os.getenv("INGESTION_JOB_ID", "").strip()
    return job_id or None


def _finalize_worker_job(
    *,
    status: str,
    message: str,
    ecs_response: dict[str, Any] | None = None,
) -> None:
    job_id = _worker_job_id()
    if not job_id:
        return
    complete_ingestion_job(
        job_id,
        status=status,
        message=message,
        ecs_response=ecs_response,
    )


def _add_teacher_parser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bucket")
    parser.add_argument("--input-prefix")
    parser.add_argument("--output-prefix")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--local-input-dir")
    parser.add_argument("--local-output-dir")
    parser.add_argument("--course-id", default=None)
    parser.add_argument("--dry-run", action="store_true")


def _add_chunk_index_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bucket")
    parser.add_argument("--input-prefix")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--local-input-dir")
    parser.add_argument("--course-id", default=None)
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--prepared-output-prefix", default=None)
    parser.add_argument("--local-output-dir", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recreate-collection", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """Build the ingestion worker CLI."""
    parser = argparse.ArgumentParser(
        description="On-demand ingestion worker for teacher uploads.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_parser = subparsers.add_parser(
        "parse",
        help="Parse teacher uploads into normalized JSON envelopes.",
    )
    _add_teacher_parser_args(parse_parser)

    chunk_parser = subparsers.add_parser(
        "chunk-index",
        help="Chunk parsed envelopes, embed them, and upsert Qdrant.",
    )
    _add_chunk_index_args(chunk_parser)

    return parser


def _embedding_dimension(model: SentenceTransformer) -> int:
    """Return the model's output vector size."""
    if hasattr(model, "get_sentence_embedding_dimension"):
        dim = model.get_sentence_embedding_dimension()
        if dim:
            return int(dim)

    probe = model.encode("dimension probe", show_progress_bar=False)
    if hasattr(probe, "tolist"):
        probe = probe.tolist()
    if probe and isinstance(probe[0], (list, tuple)):
        probe = probe[0]
    if not probe:
        raise RuntimeError("Unable to determine embedding dimension from model")
    return len(probe)


def _collection_vector_size(client, collection_name: str) -> int | None:
    """Inspect the stored vector size for an existing Qdrant collection."""
    info = client.get_collection(collection_name)
    vectors = getattr(info.config.params, "vectors", None)
    if vectors is None:
        return None

    size = getattr(vectors, "size", None)
    if size is not None:
        return int(size)

    if isinstance(vectors, dict) and vectors:
        first_vector = next(iter(vectors.values()))
        size = getattr(first_vector, "size", None)
        if size is not None:
            return int(size)

    return None


def _ensure_collection(
    client,
    collection_name: str,
    *,
    recreate: bool,
    vector_size: int,
) -> bool:
    """Create the target collection if needed and add common payload indexes."""
    exists = client.collection_exists(collection_name)
    if exists:
        current_size = _collection_vector_size(client, collection_name)
        if current_size is not None and current_size != vector_size:
            if not recreate:
                raise SystemExit(
                    "ERROR: Qdrant collection "
                    f"{collection_name!r} has dim={current_size}, "
                    f"expected dim={vector_size}. "
                    "Recreate the collection or rerun with --recreate-collection.",
                )
            client.delete_collection(collection_name)
            exists = False
        elif recreate:
            client.delete_collection(collection_name)
            exists = False

    if exists:
        return False

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.DOT),
    )

    index_specs = (
        ("week", PayloadSchemaType.INTEGER),
        ("category", PayloadSchemaType.KEYWORD),
        ("priority", PayloadSchemaType.INTEGER),
        ("source_domain", PayloadSchemaType.KEYWORD),
        ("source_type", PayloadSchemaType.KEYWORD),
        ("course_id", PayloadSchemaType.KEYWORD),
    )
    for field_name, schema in index_specs:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception:
            continue

    return True


def _discover_s3_objects(s3, bucket: str, prefix: str) -> list[dict[str, str]]:
    """List JSON objects under an S3 prefix."""
    items: list[dict[str, str]] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not key.lower().endswith(".json"):
                continue
            items.append({"key": key, "name": os.path.basename(key)})
        if response.get("IsTruncated"):
            token = response.get("NextContinuationToken")
        else:
            break
    return items


def _load_envelopes_from_s3(
    *,
    bucket: str,
    input_prefix: str,
    profile: str | None,
    region: str,
) -> list[dict[str, Any]]:
    import boto3  # noqa: WPS433

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")
    envelopes: list[dict[str, Any]] = []
    for obj in _discover_s3_objects(s3, bucket, input_prefix):
        response = s3.get_object(Bucket=bucket, Key=obj["key"])
        body = response["Body"].read().decode("utf-8")
        envelopes.append(json.loads(body))
    return envelopes


def _write_json_local(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json_s3(
    *,
    s3,
    bucket: str,
    key: str,
    data: dict[str, Any],
) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(json.dumps(data, ensure_ascii=False, indent=2))
    try:
        s3.upload_file(
            str(tmp_path),
            bucket,
            key,
            ExtraArgs={
                "ServerSideEncryption": "AES256",
                "ContentType": "application/json",
            },
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _build_points(
    *,
    records,
    model: SentenceTransformer,
) -> list[PointStruct]:
    points: list[PointStruct] = []
    for record in records:
        vector = model.encode(
            record.chunk.content,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        else:
            vector = list(vector)
        points.append(
            PointStruct(
                id=record.chunk.chunk_id,
                vector=vector,
                payload=record.payload,
            )
        )
    return points


def _collection_for_args(runtime, args: argparse.Namespace, envelopes: list[dict[str, Any]]) -> str:
    if args.collection_name:
        return str(args.collection_name)
    if args.course_id:
        return runtime.collection_for(str(args.course_id))
    if envelopes:
        course_id = str(envelopes[0].get("course_id", "")).strip()
        if course_id:
            return runtime.collection_for(course_id)
    raise SystemExit("ERROR: chunk-index needs --collection-name, --course-id, or parsed envelopes with course_id")


def _prepared_output_for_envelope(
    *,
    envelope: dict[str, Any],
    local_output_dir: str | None,
    prepared_output_prefix: str | None,
) -> tuple[str | None, Path | None]:
    artifact_name = prepared_chunk_artifact_name(envelope)
    if local_output_dir:
        return None, Path(local_output_dir) / artifact_name
    if prepared_output_prefix:
        prefix = prepared_output_prefix.rstrip("/")
        course_id = str(envelope.get("course_id", "unknown")).strip() or "unknown"
        return f"{prefix}/{course_id}/{artifact_name}", None
    return None, None


def run_parse(args: argparse.Namespace) -> None:
    """Delegate to the existing parser CLI."""
    teacher_parser.run(args)


def run_chunk_index(
    args: argparse.Namespace,
    *,
    client=None,
    model: SentenceTransformer | None = None,
) -> ChunkIndexSummary:
    """Chunk parsed envelopes and upsert them into Qdrant."""
    runtime = get_runtime_config()
    local_mode = bool(args.local_input_dir)

    if local_mode:
        if any([args.bucket, args.input_prefix, args.profile]):
            raise SystemExit("ERROR: do not mix local input with S3 discovery flags")
        envelopes = load_parsed_envelopes_from_dir(args.local_input_dir)
    else:
        if not (args.bucket and args.input_prefix):
            raise SystemExit("ERROR: chunk-index needs --bucket and --input-prefix in S3 mode")
        envelopes = _load_envelopes_from_s3(
            bucket=args.bucket,
            input_prefix=args.input_prefix,
            profile=args.profile,
            region=args.region,
        )

    if not envelopes:
        collection_name = _collection_for_args(runtime, args, envelopes)
        return ChunkIndexSummary(
            collection_name=collection_name,
            envelopes_processed=0,
            chunks_indexed=0,
            created_collection=False,
            prepared_artifacts_written=0,
        )

    collection_name = _collection_for_args(runtime, args, envelopes)
    qdrant_client = client or create_qdrant_client(runtime)
    embedding_model = model or SentenceTransformer(
        args.embedding_model or runtime.embedding_model,
    )
    vector_size = _embedding_dimension(embedding_model)

    created_collection = _ensure_collection(
        qdrant_client,
        collection_name,
        recreate=bool(args.recreate_collection),
        vector_size=vector_size,
    )

    envelopes_processed = 0
    chunks_indexed = 0
    prepared_artifacts_written = 0

    if args.dry_run:
        for envelope in envelopes:
            records = build_chunk_records_from_envelope(envelope)
            print(
                f"  {envelope.get('file_name', 'document')}: "
                f"{len(records)} chunks -> {collection_name}",
            )
        return ChunkIndexSummary(
            collection_name=collection_name,
            envelopes_processed=len(envelopes),
            chunks_indexed=sum(
                len(build_chunk_records_from_envelope(envelope))
                for envelope in envelopes
            ),
            created_collection=created_collection,
            prepared_artifacts_written=0,
        )

    if local_mode:
        local_output_dir = args.local_output_dir
        s3 = None
    else:
        local_output_dir = None
        s3 = None
        if args.prepared_output_prefix:
            import boto3  # noqa: WPS433

            session = boto3.Session(profile_name=args.profile, region_name=args.region)
            s3 = session.client("s3")

    for envelope in envelopes:
        records = build_chunk_records_from_envelope(envelope)
        if not records:
            continue

        envelopes_processed += 1
        points = _build_points(records=records, model=embedding_model)

        batch_size = 100
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            qdrant_client.upsert(collection_name=collection_name, points=batch)

        chunks_indexed += len(points)

        prepared_key, prepared_path = _prepared_output_for_envelope(
            envelope=envelope,
            local_output_dir=local_output_dir,
            prepared_output_prefix=args.prepared_output_prefix,
        )
        if prepared_path is not None:
            prepared_document = build_prepared_chunk_document(
                envelope=envelope,
                records=records,
            )
            _write_json_local(prepared_path, prepared_document)
            prepared_artifacts_written += 1
        elif prepared_key is not None and s3 is not None:
            prepared_document = build_prepared_chunk_document(
                envelope=envelope,
                records=records,
            )
            _write_json_s3(
                s3=s3,
                bucket=args.bucket,
                key=prepared_key,
                data=prepared_document,
            )
            prepared_artifacts_written += 1

    return ChunkIndexSummary(
        collection_name=collection_name,
        envelopes_processed=envelopes_processed,
        chunks_indexed=chunks_indexed,
        created_collection=created_collection,
        prepared_artifacts_written=prepared_artifacts_written,
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse":
        try:
            run_parse(args)
        except Exception as exc:
            _finalize_worker_job(status="failed", message=str(exc))
            raise
        _finalize_worker_job(
            status="completed",
            message="Parsed envelopes written successfully.",
        )
        return

    if args.command == "chunk-index":
        try:
            summary = run_chunk_index(args)
        except Exception as exc:
            _finalize_worker_job(status="failed", message=str(exc))
            raise
        summary_payload = {
            "collection_name": summary.collection_name,
            "envelopes_processed": summary.envelopes_processed,
            "chunks_indexed": summary.chunks_indexed,
            "created_collection": summary.created_collection,
            "prepared_artifacts_written": summary.prepared_artifacts_written,
        }
        print(json.dumps(summary_payload, indent=2))
        _finalize_worker_job(
            status="completed",
            message=(
                "Indexed "
                f"{summary.chunks_indexed} chunk(s) into {summary.collection_name}."
            ),
            ecs_response=summary_payload,
        )
        return

    raise SystemExit(f"ERROR: unknown command {args.command!r}")


if __name__ == "__main__":
    main()
