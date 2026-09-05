from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import (
    Chunk,
    Citation,
    Company,
    Document,
    Embedding,
    RetrievalResult,
)
from fdre.retrieval.scope import retrieval_indexable_document_clause


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit of research-archive contamination in live retrieval state"
    )
    parser.add_argument("--database-url")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def build_archive_scope_audit(session: Session) -> dict[str, Any]:
    settings = get_settings()
    archive_documents = select(Document.id).where(
        ~retrieval_indexable_document_clause()
    )
    archive_chunks = select(Chunk.id).where(Chunk.document_id.in_(archive_documents))

    archive_document_count = session.scalar(
        select(func.count()).select_from(Document).where(
            ~retrieval_indexable_document_clause()
        )
    ) or 0
    archive_chunk_count = session.scalar(
        select(func.count()).select_from(Chunk).where(
            Chunk.document_id.in_(archive_documents)
        )
    ) or 0
    archive_embedding_count = session.scalar(
        select(func.count()).select_from(Embedding).where(
            Embedding.chunk_id.in_(archive_chunks)
        )
    ) or 0
    retrieval_result_references = session.scalar(
        select(func.count()).select_from(RetrievalResult).where(
            RetrievalResult.chunk_id.in_(archive_chunks)
        )
    ) or 0
    citation_references = session.scalar(
        select(func.count()).select_from(Citation).where(
            Citation.chunk_id.in_(archive_chunks)
        )
    ) or 0

    provider_rows = session.execute(
        select(
            Embedding.provider,
            Embedding.model,
            Embedding.dimensions,
            func.count().label("embedding_count"),
        )
        .where(Embedding.chunk_id.in_(archive_chunks))
        .group_by(Embedding.provider, Embedding.model, Embedding.dimensions)
        .order_by(Embedding.provider, Embedding.model, Embedding.dimensions)
    ).all()

    top_company_rows = session.execute(
        select(
            Company.id,
            Company.ticker,
            Company.cik,
            func.count(Chunk.id).label("chunk_count"),
        )
        .join(Document, Document.company_id == Company.id)
        .join(Chunk, Chunk.document_id == Document.id)
        .where(~retrieval_indexable_document_clause())
        .group_by(Company.id, Company.ticker, Company.cik)
        .order_by(func.count(Chunk.id).desc(), Company.id)
        .limit(25)
    ).all()

    matching_embedding = exists().where(
        Embedding.chunk_id == Chunk.id,
        Embedding.provider == settings.embedding_provider,
        Embedding.model == settings.embedding_model,
    )
    if settings.embedding_dimensions is not None:
        matching_embedding = matching_embedding.where(
            Embedding.dimensions == settings.embedding_dimensions
        )
    online_missing_embeddings = session.scalar(
        select(func.count())
        .select_from(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            retrieval_indexable_document_clause(),
            ~matching_embedding,
        )
    ) or 0

    return {
        "schema_version": "fdre-retrieval-archive-scope-audit-v1",
        "read_only": True,
        "archive_profile": "fdre-research-archive-v1",
        "archive_documents": int(archive_document_count),
        "archive_chunks": int(archive_chunk_count),
        "archive_embeddings": int(archive_embedding_count),
        "archive_retrieval_result_references": int(retrieval_result_references),
        "archive_citation_references": int(citation_references),
        "archive_embeddings_by_provider": [
            {
                "provider": str(row.provider),
                "model": str(row.model),
                "dimensions": int(row.dimensions),
                "count": int(row.embedding_count),
            }
            for row in provider_rows
        ],
        "top_archive_chunk_companies": [
            {
                "company_id": int(row.id),
                "ticker": row.ticker,
                "cik": str(row.cik),
                "chunk_count": int(row.chunk_count),
            }
            for row in top_company_rows
        ],
        "configured_embedding": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
        },
        "retrieval_indexable_chunks_missing_configured_embedding": int(
            online_missing_embeddings
        ),
    }


def main() -> None:
    args = parse_args()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            payload = build_archive_scope_audit(session)
    finally:
        engine.dispose()

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
