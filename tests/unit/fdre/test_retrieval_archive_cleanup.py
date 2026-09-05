from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import (
    AnswerRun,
    Chunk,
    Citation,
    Company,
    Document,
    DocumentElement,
    Embedding,
    RetrievalResult,
    RetrievalRun,
)
from fdre.retrieval.scope import RESEARCH_ARCHIVE_PROFILE
from scripts.ingestion import cleanup_retrieval_archive_scope as cleanup


def _patch_expected_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cleanup, "EXPECTED_ARCHIVE_DOCUMENTS", 1)
    monkeypatch.setattr(cleanup, "EXPECTED_ARCHIVE_CHUNKS", 2)
    monkeypatch.setattr(cleanup, "EXPECTED_ARCHIVE_EMBEDDINGS", 1)
    monkeypatch.setattr(cleanup, "EXPECTED_RETRIEVAL_REFERENCES", 0)
    monkeypatch.setattr(cleanup, "EXPECTED_CITATION_REFERENCES", 0)


def _seed_scope_state(session: Session) -> tuple[Document, Document, list[Chunk]]:
    company = Company(ticker="TEST", cik="0000000001", name="Cleanup Test Co.")
    online = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0000000001-26-000001",
    )
    online_element = DocumentElement(
        document=online,
        element_type="text",
        section="Risk Factors",
        text="online disclosure",
        reading_order=1,
    )
    archive = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0000000001-12-000001",
        metadata_json={
            "research_archive": {
                "profile": RESEARCH_ARCHIVE_PROFILE,
                "sections": ["Risk Factors"],
            }
        },
    )
    archive_element = DocumentElement(
        document=archive,
        element_type="text",
        section="Risk Factors",
        text="archive disclosure",
        reading_order=1,
    )
    session.add(company)
    session.flush()

    online_chunk = Chunk(
        document=online,
        element=online_element,
        chunk_text="online disclosure",
        chunk_type="text",
        section="Risk Factors",
        token_count=2,
    )
    archive_chunks = [
        Chunk(
            document=archive,
            element=archive_element,
            chunk_text=f"archive disclosure {index}",
            chunk_type="text",
            section="Risk Factors",
            token_count=3,
        )
        for index in (1, 2)
    ]
    session.add_all([online_chunk, *archive_chunks])
    session.flush()
    session.add_all(
        [
            Embedding(
                chunk=online_chunk,
                provider="voyage",
                model="voyage-4-large",
                dimensions=2,
                vector=[0.1, 0.2],
            ),
            Embedding(
                chunk=archive_chunks[0],
                provider="voyage",
                model="voyage-4-large",
                dimensions=2,
                vector=[0.3, 0.4],
            ),
        ]
    )
    session.commit()
    return online, archive, [online_chunk, *archive_chunks]


def test_projection_is_deterministic_and_does_not_mutate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_expected_counts(monkeypatch)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_scope_state(session)
        before = cleanup.snapshot_cleanup_state(session)
        first = cleanup.run_cleanup(
            session,
            apply=False,
            resume=False,
            batch_size=1,
            output=tmp_path / "projection.json",
        )
        second = cleanup.run_cleanup(
            session,
            apply=False,
            resume=False,
            batch_size=1,
        )
        after = cleanup.snapshot_cleanup_state(session)

        assert first["applied"] is False
        assert first["mode"] == "projection"
        assert first["plan_id"] == second["plan_id"]
        assert before == after
        assert after.archive_chunks == 2
        assert after.archive_embeddings == 1

    engine.dispose()


def test_apply_requires_explicit_production_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_expected_counts(monkeypatch)
    monkeypatch.delenv("FDRE_ALLOW_PROD", raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_scope_state(session)
        with pytest.raises(RuntimeError, match="FDRE_ALLOW_PROD=1"):
            cleanup.run_cleanup(
                session,
                apply=True,
                resume=False,
                batch_size=1,
            )
        assert cleanup.snapshot_cleanup_state(session).archive_chunks == 2

    engine.dispose()


def test_non_resume_rejects_frozen_count_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_expected_counts(monkeypatch)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _, _, chunks = _seed_scope_state(session)
        session.delete(chunks[-1])
        session.commit()
        with pytest.raises(RuntimeError, match="archive chunk count drifted"):
            cleanup.run_cleanup(
                session,
                apply=False,
                resume=False,
                batch_size=1,
            )

    engine.dispose()


def test_cleanup_refuses_retrieval_or_citation_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_counts(monkeypatch)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _, _, chunks = _seed_scope_state(session)
        archive_chunk = chunks[1]
        retrieval_run = RetrievalRun(
            query="archive",
            retriever_variant="hybrid",
        )
        retrieval_run.results.append(
            RetrievalResult(chunk=archive_chunk, rank=1)
        )
        answer_run = AnswerRun(question="archive")
        answer_run.citations.append(
            Citation(
                chunk=archive_chunk,
                claim_text="claim",
                citation_text="citation",
            )
        )
        session.add_all([retrieval_run, answer_run])
        session.commit()

        with pytest.raises(RuntimeError, match="retrieval-result references"):
            cleanup.run_cleanup(
                session,
                apply=False,
                resume=False,
                batch_size=1,
            )

    engine.dispose()


def test_apply_deletes_only_archive_retrieval_state_and_preserves_archive_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_expected_counts(monkeypatch)
    monkeypatch.setenv("FDRE_ALLOW_PROD", "1")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        online, archive, chunks = _seed_scope_state(session)
        online_chunk_id = chunks[0].id
        archive_id = archive.id
        archive_element_ids = list(
            session.scalars(
                select(DocumentElement.id).where(DocumentElement.document_id == archive_id)
            )
        )

        report = cleanup.run_cleanup(
            session,
            apply=True,
            resume=False,
            batch_size=1,
            output=tmp_path / "apply.json",
        )

        assert report["applied"] is True
        assert report["complete"] is True
        assert report["progress"] == {
            "deleted_chunks": 2,
            "deleted_embeddings": 1,
            "batches_committed": 2,
        }
        assert cleanup.snapshot_cleanup_state(session) == cleanup.CleanupSnapshot(
            archive_documents=1,
            archive_chunks=0,
            archive_embeddings=0,
            retrieval_result_references=0,
            citation_references=0,
        )
        assert session.get(Document, archive_id) is not None
        assert session.scalar(
            select(func.count()).select_from(DocumentElement).where(
                DocumentElement.id.in_(archive_element_ids)
            )
        ) == len(archive_element_ids)
        assert session.get(Document, online.id) is not None
        assert session.get(Chunk, online_chunk_id) is not None
        assert session.scalar(
            select(func.count()).select_from(Embedding).where(
                Embedding.chunk_id == online_chunk_id
            )
        ) == 1

    engine.dispose()


def test_resume_allows_only_a_partial_frozen_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_expected_counts(monkeypatch)
    monkeypatch.setenv("FDRE_ALLOW_PROD", "1")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _, _, chunks = _seed_scope_state(session)
        archive_chunk_with_embedding = chunks[1]
        session.execute(
            Embedding.__table__.delete().where(
                Embedding.chunk_id == archive_chunk_with_embedding.id
            )
        )
        session.delete(archive_chunk_with_embedding)
        session.commit()

        partial = cleanup.snapshot_cleanup_state(session)
        assert partial.archive_chunks == 1
        assert partial.archive_embeddings == 0

        report = cleanup.run_cleanup(
            session,
            apply=True,
            resume=True,
            batch_size=1,
        )

        assert report["complete"] is True
        assert report["progress"]["deleted_chunks"] == 1
        assert cleanup.snapshot_cleanup_state(session).archive_chunks == 0

    engine.dispose()
