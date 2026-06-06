from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base

if TYPE_CHECKING:
    from apps.api.app.models.documents import Chunk

JSONDict = dict[str, Any]


class AnswerRun(Base):
    __tablename__ = "answer_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    rewritten_queries_json: Mapped[list[str] | None] = mapped_column(JSON)
    route_json: Mapped[JSONDict | None] = mapped_column(JSON)
    answer_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abstention_reason: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    trace_json: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    citations: Mapped[list[Citation]] = relationship(
        back_populates="answer_run",
        cascade="all, delete-orphan",
    )


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_run_id: Mapped[int] = mapped_column(
        ForeignKey("answer_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id"), index=True, nullable=False)
    claim_text: Mapped[str] = mapped_column(Text)
    citation_text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    answer_run: Mapped[AnswerRun] = relationship(back_populates="citations")
    chunk: Mapped[Chunk] = relationship()
