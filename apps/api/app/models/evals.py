from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base

JSONDict = dict[str, Any]


class EvalQuestion(Base):
    __tablename__ = "eval_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_key: Mapped[str | None] = mapped_column(String(128), index=True, unique=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    split: Mapped[str | None] = mapped_column(String(32), index=True)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    expected_tickers_json: Mapped[list[str] | None] = mapped_column(JSON)
    expected_sections_json: Mapped[list[str] | None] = mapped_column(JSON)
    relevant_evidence_json: Mapped[list[JSONDict] | None] = mapped_column(JSON)
    relevant_chunk_ids_json: Mapped[list[int] | None] = mapped_column(JSON)
    answer_type: Mapped[str | None] = mapped_column(String(64))
    should_abstain: Mapped[bool | None]
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[JSONDict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
