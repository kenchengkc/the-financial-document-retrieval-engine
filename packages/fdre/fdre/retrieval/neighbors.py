"""Neighbor chunk expansion.

A retrieved chunk is often a fragment of a larger passage. Pulling the
immediately adjacent chunks from the same document (in reading order) gives the
answer generator complete context — the sentence before/after a hit — without
widening the ranked candidate set used for the confidence gate.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
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
    document_of: dict[int, int] = {
        row.id: row.document_id
        for row in session.execute(
            select(Chunk.id, Chunk.document_id).where(Chunk.id.in_(list(existing)))
        )
    }
    neighbor_ids: set[int] = set()
    for candidate in candidates:
        document_id = document_of.get(candidate.chunk_id)
        if document_id is None:
            continue
        previous = session.execute(
            select(Chunk.id)
            .where(Chunk.document_id == document_id, Chunk.id < candidate.chunk_id)
            .order_by(Chunk.id.desc())
            .limit(window)
        ).scalars()
        following = session.execute(
            select(Chunk.id)
            .where(Chunk.document_id == document_id, Chunk.id > candidate.chunk_id)
            .order_by(Chunk.id.asc())
            .limit(window)
        ).scalars()
        neighbor_ids.update(previous)
        neighbor_ids.update(following)
    neighbor_ids -= existing
    if not neighbor_ids:
        return list(candidates)

    chunks = session.execute(select(Chunk).where(Chunk.id.in_(neighbor_ids))).scalars().all()
    additions = [
        RetrievalCandidate(
            chunk_id=chunk.id,
            text=chunk.chunk_text,
            metadata={**(chunk.metadata_json or {}), "neighbor_expanded": True},
        )
        for chunk in sorted(chunks, key=lambda chunk: chunk.id)
    ]
    return [*candidates, *additions]
