from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models import Chunk, Document, DocumentElement


class ChunkSpec(BaseModel):
    chunk_text: str
    chunk_type: str
    section: str | None
    page_start: int | None
    page_end: int | None
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ElementChunker:
    """Split document text elements without crossing source-element boundaries."""

    def __init__(self, max_tokens: int = 220) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens

    def chunk(
        self,
        element: DocumentElement,
        *,
        metadata: dict[str, Any],
    ) -> list[ChunkSpec]:
        if element.element_type == "table":
            return []

        text = (element.text or "").strip()
        if not text:
            return []

        chunks: list[ChunkSpec] = []
        for index, token_group in enumerate(_groups(text.split(), self.max_tokens)):
            chunk_text = " ".join(token_group)
            chunks.append(
                ChunkSpec(
                    chunk_text=chunk_text,
                    chunk_type="text",
                    section=element.section,
                    page_start=element.page_number,
                    page_end=element.page_number,
                    token_count=len(token_group),
                    metadata={
                        **metadata,
                        "source_element_type": element.element_type,
                        "element_chunk_index": index,
                    },
                )
            )
        return chunks


def document_chunk_metadata(document: Document, element: DocumentElement) -> dict[str, Any]:
    return {
        "ticker": document.company.ticker,
        "cik": document.company.cik,
        "company_name": document.company.name,
        "form_type": document.form_type,
        "filing_date": document.filing_date.isoformat() if document.filing_date else None,
        "accession_number": document.accession_number,
        "section": element.section,
        "page_number": element.page_number,
        "element_type": element.element_type,
        "document_id": document.id,
        "element_id": element.id,
    }


def rebuild_document_chunks(
    session: Session,
    document_id: int,
    *,
    max_tokens: int = 220,
) -> list[Chunk]:
    from fdre.chunking.table_chunker import TableChunker

    document = session.scalar(
        select(Document)
        .options(joinedload(Document.company), joinedload(Document.elements))
        .where(Document.id == document_id)
    )
    if document is None:
        raise ValueError(f"Document {document_id} does not exist")

    for existing_chunk in list(document.chunks):
        session.delete(existing_chunk)
    session.flush()

    text_chunker = ElementChunker(max_tokens=max_tokens)
    table_chunker = TableChunker()
    stored: list[Chunk] = []
    elements = sorted(
        document.elements,
        key=lambda element: (
            element.reading_order is None,
            element.reading_order or 0,
            element.id,
        ),
    )
    for element in elements:
        metadata = document_chunk_metadata(document, element)
        specs = (
            table_chunker.chunk(element, metadata=metadata)
            if element.element_type == "table"
            else text_chunker.chunk(element, metadata=metadata)
        )
        for spec in specs:
            chunk = Chunk(
                document=document,
                element=element,
                chunk_text=spec.chunk_text,
                chunk_type=spec.chunk_type,
                section=spec.section,
                page_start=spec.page_start,
                page_end=spec.page_end,
                token_count=spec.token_count,
                metadata_json=spec.metadata,
            )
            session.add(chunk)
            stored.append(chunk)

    session.commit()
    return stored


def _groups(tokens: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(tokens), size):
        yield tokens[start : start + size]
