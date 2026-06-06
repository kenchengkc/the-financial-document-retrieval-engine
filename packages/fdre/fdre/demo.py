from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.chunking import rebuild_document_chunks
from fdre.indexing.embeddings import (
    EmbeddingProvider,
    embedding_provider_from_settings,
    rebuild_embeddings,
)
from fdre.parsing.html_filing_parser import HtmlFilingParser


def seed_demo_document(
    session: Session,
    *,
    fixture_path: Path | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, int]:
    path = fixture_path or Path("data/sample/sec_filing.html")
    company = session.scalar(select(Company).where(Company.ticker == "EXMPL"))
    if company is None:
        company = Company(
            ticker="EXMPL",
            cik="0000000001",
            name="Example Company",
            exchange="SAMPLE",
        )
        session.add(company)
        session.flush()

    document = session.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.accession_number == "0000000001-25-000001",
        )
    )
    if document is None:
        document = Document(
            company=company,
            source_type="sample",
            form_type="10-K",
            filing_date=date(2025, 12, 31),
            accession_number="0000000001-25-000001",
            source_url="data/sample/sec_filing.html",
            local_path=str(path),
        )
        session.add(document)
        session.flush()
    else:
        element_count = session.scalar(
            select(func.count())
            .select_from(DocumentElement)
            .where(DocumentElement.document_id == document.id)
        ) or 0
        chunk_count = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == document.id)
        ) or 0
        embedding_count = session.scalar(
            select(func.count())
            .select_from(Embedding)
            .join(Chunk, Chunk.id == Embedding.chunk_id)
            .where(Chunk.document_id == document.id)
        ) or 0
        if element_count and chunk_count and embedding_count == chunk_count:
            return {
                "documents": 1,
                "elements": element_count,
                "chunks": chunk_count,
                "embeddings": embedding_count,
            }
        chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
        session.execute(delete(Embedding).where(Embedding.chunk_id.in_(chunk_ids)))
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.execute(
            delete(DocumentElement).where(DocumentElement.document_id == document.id)
        )

    parsed = HtmlFilingParser().parse_file(path)
    session.add_all(
        [
            DocumentElement(
                document_id=document.id,
                element_type=element.element_type,
                page_number=element.page_number,
                section=element.section,
                text=element.text,
                markdown=element.markdown,
                json_payload=element.metadata,
                bbox=element.bbox,
                reading_order=element.reading_order,
            )
            for element in parsed
        ]
    )
    session.commit()
    chunks = rebuild_document_chunks(session, document.id)
    embeddings = rebuild_embeddings(
        session,
        provider or embedding_provider_from_settings(get_settings()),
        chunk_ids=[chunk.id for chunk in chunks],
    )
    return {
        "documents": 1,
        "elements": len(parsed),
        "chunks": len(chunks),
        "embeddings": embeddings,
    }
