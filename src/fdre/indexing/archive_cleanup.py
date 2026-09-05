from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Citation, Document, Embedding, RetrievalResult
from fdre.retrieval.scope import (
    RESEARCH_ARCHIVE_PROFILE,
    retrieval_indexable_document_clause,
)

FROZEN_AUDIT_RUN_ID = 33991763800
FROZEN_AUDIT_ARTIFACT_ID = 9976877257
FROZEN_AUDIT_SHA256 = (
    "f3fe063f354892929a9f3858505e752ea8d1377a90d266a08a906de5872e1309"
)
EXPECTED_ARCHIVE_DOCUMENTS = 10_032
EXPECTED_ARCHIVE_CHUNKS = 1_164_008
EXPECTED_ARCHIVE_EMBEDDINGS = 44_416
EXPECTED_RETRIEVAL_REFERENCES = 0
EXPECTED_CITATION_REFERENCES = 0
DEFAULT_BATCH_SIZE = 10_000
SCHEMA_VERSION = "fdre-retrieval-archive-cleanup-v1"


@dataclass(frozen=True, slots=True)
class CleanupSnapshot:
    archive_documents: int
    archive_chunks: int
    archive_embeddings: int
    retrieval_result_references: int
    citation_references: int


@dataclass(frozen=True, slots=True)
class CleanupProgress:
    deleted_chunks: int = 0
    deleted_embeddings: int = 0
    batches_committed: int = 0


def _archive_document_ids() -> Any:
    return select(Document.id).where(~retrieval_indexable_document_clause())


def _archive_chunk_ids() -> Any:
    return select(Chunk.id).where(Chunk.document_id.in_(_archive_document_ids()))


def snapshot_cleanup_state(session: Session) -> CleanupSnapshot:
    archive_documents = session.scalar(
        select(func.count()).select_from(Document).where(
            ~retrieval_indexable_document_clause()
        )
    ) or 0
    archive_chunks = session.scalar(
        select(func.count()).select_from(Chunk).where(
            Chunk.document_id.in_(_archive_document_ids())
        )
    ) or 0
    archive_embeddings = session.scalar(
        select(func.count()).select_from(Embedding).where(
            Embedding.chunk_id.in_(_archive_chunk_ids())
        )
    ) or 0
    retrieval_result_references = session.scalar(
        select(func.count()).select_from(RetrievalResult).where(
            RetrievalResult.chunk_id.in_(_archive_chunk_ids())
        )
    ) or 0
    citation_references = session.scalar(
        select(func.count()).select_from(Citation).where(
            Citation.chunk_id.in_(_archive_chunk_ids())
        )
    ) or 0
    return CleanupSnapshot(
        archive_documents=int(archive_documents),
        archive_chunks=int(archive_chunks),
        archive_embeddings=int(archive_embeddings),
        retrieval_result_references=int(retrieval_result_references),
        citation_references=int(citation_references),
    )


def validate_cleanup_prestate(snapshot: CleanupSnapshot, *, resume: bool) -> None:
    if snapshot.archive_documents != EXPECTED_ARCHIVE_DOCUMENTS:
        raise RuntimeError(
            "archive document count drifted: "
            f"expected {EXPECTED_ARCHIVE_DOCUMENTS}, got {snapshot.archive_documents}"
        )
    if snapshot.retrieval_result_references != EXPECTED_RETRIEVAL_REFERENCES:
        raise RuntimeError(
            "archive chunks have retrieval-result references; refusing cleanup: "
            f"{snapshot.retrieval_result_references}"
        )
    if snapshot.citation_references != EXPECTED_CITATION_REFERENCES:
        raise RuntimeError(
            "archive chunks have citation references; refusing cleanup: "
            f"{snapshot.citation_references}"
        )

    if not resume:
        if snapshot.archive_chunks != EXPECTED_ARCHIVE_CHUNKS:
            raise RuntimeError(
                "archive chunk count drifted: "
                f"expected {EXPECTED_ARCHIVE_CHUNKS}, got {snapshot.archive_chunks}"
            )
        if snapshot.archive_embeddings != EXPECTED_ARCHIVE_EMBEDDINGS:
            raise RuntimeError(
                "archive embedding count drifted: "
                f"expected {EXPECTED_ARCHIVE_EMBEDDINGS}, got {snapshot.archive_embeddings}"
            )
        return

    if not 0 <= snapshot.archive_chunks <= EXPECTED_ARCHIVE_CHUNKS:
        raise RuntimeError(
            "resume archive chunk count is outside the frozen baseline: "
            f"{snapshot.archive_chunks}"
        )
    if not 0 <= snapshot.archive_embeddings <= EXPECTED_ARCHIVE_EMBEDDINGS:
        raise RuntimeError(
            "resume archive embedding count is outside the frozen baseline: "
            f"{snapshot.archive_embeddings}"
        )


def cleanup_plan_id(snapshot: CleanupSnapshot, *, resume: bool, batch_size: int) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "archive_profile": RESEARCH_ARCHIVE_PROFILE,
        "frozen_audit": {
            "run_id": FROZEN_AUDIT_RUN_ID,
            "artifact_id": FROZEN_AUDIT_ARTIFACT_ID,
            "sha256": FROZEN_AUDIT_SHA256,
        },
        "expected": {
            "archive_documents": EXPECTED_ARCHIVE_DOCUMENTS,
            "archive_chunks": EXPECTED_ARCHIVE_CHUNKS,
            "archive_embeddings": EXPECTED_ARCHIVE_EMBEDDINGS,
            "retrieval_result_references": EXPECTED_RETRIEVAL_REFERENCES,
            "citation_references": EXPECTED_CITATION_REFERENCES,
        },
        "observed_before": asdict(snapshot),
        "resume": resume,
        "batch_size": batch_size,
        "preserve": ["documents", "document_elements"],
        "delete": ["archive_embeddings", "archive_chunks"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _locked_archive_chunk_batch(session: Session, *, batch_size: int) -> list[int]:
    statement = (
        select(Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(~retrieval_indexable_document_clause())
        .order_by(Chunk.id)
        .limit(batch_size)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(of=Chunk)
    return [int(chunk_id) for chunk_id in session.scalars(statement)]


def _batch_reference_counts(session: Session, chunk_ids: list[int]) -> tuple[int, int]:
    retrieval_references = session.scalar(
        select(func.count()).select_from(RetrievalResult).where(
            RetrievalResult.chunk_id.in_(chunk_ids)
        )
    ) or 0
    citation_references = session.scalar(
        select(func.count()).select_from(Citation).where(
            Citation.chunk_id.in_(chunk_ids)
        )
    ) or 0
    return int(retrieval_references), int(citation_references)


def _delete_batch(session: Session, chunk_ids: list[int]) -> tuple[int, int]:
    retrieval_references, citation_references = _batch_reference_counts(session, chunk_ids)
    if retrieval_references or citation_references:
        session.rollback()
        raise RuntimeError(
            "archive chunk references appeared during cleanup; refusing batch: "
            f"retrieval_results={retrieval_references}, citations={citation_references}"
        )

    embedding_result = session.execute(
        delete(Embedding).where(Embedding.chunk_id.in_(chunk_ids))
    )
    chunk_result = session.execute(delete(Chunk).where(Chunk.id.in_(chunk_ids)))
    deleted_embeddings = int(getattr(embedding_result, "rowcount", 0) or 0)
    deleted_chunks = int(getattr(chunk_result, "rowcount", 0) or 0)
    if deleted_chunks != len(chunk_ids):
        session.rollback()
        raise RuntimeError(
            "archive cleanup batch row count mismatch: "
            f"selected={len(chunk_ids)}, deleted={deleted_chunks}"
        )
    session.commit()
    return deleted_chunks, deleted_embeddings


def _report_payload(
    *,
    mode: str,
    applied: bool,
    before: CleanupSnapshot,
    after: CleanupSnapshot,
    progress: CleanupProgress,
    plan_id: str,
    resume: bool,
    batch_size: int,
    complete: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "applied": applied,
        "complete": complete,
        "archive_profile": RESEARCH_ARCHIVE_PROFILE,
        "frozen_audit": {
            "run_id": FROZEN_AUDIT_RUN_ID,
            "artifact_id": FROZEN_AUDIT_ARTIFACT_ID,
            "sha256": FROZEN_AUDIT_SHA256,
        },
        "plan_id": plan_id,
        "resume": resume,
        "batch_size": batch_size,
        "before": asdict(before),
        "after": asdict(after),
        "progress": asdict(progress),
        "preserved": {
            "archive_documents": after.archive_documents,
            "document_elements_deleted": 0,
        },
    }


def _write_report(path: Path | None, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="", flush=True)


def run_cleanup(
    session: Session,
    *,
    apply: bool,
    resume: bool,
    batch_size: int,
    output: Path | None = None,
    expected_plan_id: str | None = None,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    before = snapshot_cleanup_state(session)
    validate_cleanup_prestate(before, resume=resume)
    plan_id = cleanup_plan_id(before, resume=resume, batch_size=batch_size)
    if expected_plan_id is not None and plan_id != expected_plan_id:
        raise RuntimeError(
            f"cleanup plan ID mismatch: expected {expected_plan_id}, got {plan_id}"
        )

    if not apply:
        session.rollback()
        payload = _report_payload(
            mode="projection",
            applied=False,
            before=before,
            after=before,
            progress=CleanupProgress(),
            plan_id=plan_id,
            resume=resume,
            batch_size=batch_size,
            complete=before.archive_chunks == 0 and before.archive_embeddings == 0,
        )
        _write_report(output, payload)
        return payload

    if os.environ.get("FDRE_ALLOW_PROD") != "1":
        raise RuntimeError("--apply requires FDRE_ALLOW_PROD=1")

    progress = CleanupProgress()
    while True:
        chunk_ids = _locked_archive_chunk_batch(session, batch_size=batch_size)
        if not chunk_ids:
            break
        deleted_chunks, deleted_embeddings = _delete_batch(session, chunk_ids)
        progress = CleanupProgress(
            deleted_chunks=progress.deleted_chunks + deleted_chunks,
            deleted_embeddings=progress.deleted_embeddings + deleted_embeddings,
            batches_committed=progress.batches_committed + 1,
        )
        current = snapshot_cleanup_state(session)
        payload = _report_payload(
            mode="apply",
            applied=True,
            before=before,
            after=current,
            progress=progress,
            plan_id=plan_id,
            resume=resume,
            batch_size=batch_size,
            complete=False,
        )
        _write_report(output, payload)

    after = snapshot_cleanup_state(session)
    if after.archive_documents != EXPECTED_ARCHIVE_DOCUMENTS:
        raise RuntimeError(
            "cleanup changed archive document inventory: "
            f"expected {EXPECTED_ARCHIVE_DOCUMENTS}, got {after.archive_documents}"
        )
    if after.archive_chunks != 0 or after.archive_embeddings != 0:
        raise RuntimeError(
            "cleanup incomplete: "
            f"archive_chunks={after.archive_chunks}, "
            f"archive_embeddings={after.archive_embeddings}"
        )
    if after.retrieval_result_references or after.citation_references:
        raise RuntimeError(
            "cleanup post-state contains archive references: "
            f"retrieval_results={after.retrieval_result_references}, "
            f"citations={after.citation_references}"
        )

    payload = _report_payload(
        mode="apply",
        applied=True,
        before=before,
        after=after,
        progress=progress,
        plan_id=plan_id,
        resume=resume,
        batch_size=batch_size,
        complete=True,
    )
    _write_report(output, payload)
    return payload
