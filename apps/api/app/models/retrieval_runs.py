from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base

if TYPE_CHECKING:
    from apps.api.app.models.documents import Chunk

JSONDict = dict[str, Any]


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    filters_json: Mapped[JSONDict | None] = mapped_column(JSON)
    retriever_variant: Mapped[str] = mapped_column(String(128), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    results: Mapped[list[RetrievalResult]] = relationship(
        back_populates="retrieval_run",
        cascade="all, delete-orphan",
    )


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    retrieval_run_id: Mapped[int] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"),
        index=True,
    )
    dense_score: Mapped[float | None] = mapped_column(Float)
    sparse_score: Mapped[float | None] = mapped_column(Float)
    hybrid_score: Mapped[float | None] = mapped_column(Float)
    rerank_score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    retrieval_run: Mapped[RetrievalRun] = relationship(back_populates="results")
    chunk: Mapped[Chunk | None] = relationship()
