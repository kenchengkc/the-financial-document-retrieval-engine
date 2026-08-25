"""Neighbor chunk expansion.

A retrieved chunk is often a fragment of a larger passage. Pulling the
immediately adjacent chunks from the same document (in reading order) gives the
answer generator complete context — the sentence before/after a hit — without
widening the ranked candidate set used for the confidence gate.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk
from fdre.retrieval.query import RetrievalCandidate


def expand_with_neighbors(
    session: Session,
    candidates: Sequence[RetrievalCandidate],
    *,
    window: int = 1,
) -> list[RetrievalCandidate]:
    """Append same-document neighbor chunks (±``window``) to ``candidates``.

    Neighbors are ordered within a document by chunk id (chunks are created in
    reading order), so the previous/next chunks are the adjacent passages. The
    additions are flagged ``neighbor_expanded`` and carry no retrieval score.
    """
    if window < 1 or not candidates:
        return list(candidates)
    existing: set[int] = {candidate.chunk_id for candidate in candidates}
    candidate_rows = session.execute(
        select(Chunk.id, Chunk.document_id).where(Chunk.id.in_(list(existing)))
    ).all()
    document_ids = {row.document_id for row in candidate_rows}
    if not document_ids:
        return list(candidates)

    positioned = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id.label("document_id"),
            func.row_number()
            .over(partition_by=Chunk.document_id, order_by=Chunk.id)
            .label("position"),
        )
        .where(Chunk.document_id.in_(document_ids))
        .cte("positioned_chunks")
    )
    candidate_positions = (
        select(positioned.c.document_id, positioned.c.position)
        .where(positioned.c.chunk_id.in_(existing))
        .cte("candidate_positions")
    )
    neighbor_ids = (
        select(positioned.c.chunk_id)
        .join(
            candidate_positions,
            and_(
                positioned.c.document_id == candidate_positions.c.document_id,
                positioned.c.position >= candidate_positions.c.position - window,
                positioned.c.position <= candidate_positions.c.position + window,
            ),
        )
        .where(positioned.c.chunk_id.not_in(existing))
        .distinct()
    )
    chunks = list(
        session.scalars(
            select(Chunk).where(Chunk.id.in_(neighbor_ids)).order_by(Chunk.id)
        )
    )
    additions = [
        RetrievalCandidate(
            chunk_id=chunk.id,
            text=chunk.chunk_text,
            metadata={**(chunk.metadata_json or {}), "neighbor_expanded": True},
        )
        for chunk in chunks
    ]
    return [*candidates, *additions]
