from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.db import Base


class AnswerCache(Base):
    """Cached ``/answer`` responses.

    Keyed by a hash of the normalized question plus a pipeline-config version, so
    any change to the embedding/rerank/answer settings yields a fresh key. A short
    TTL (``ANSWER_CACHE_TTL_SECONDS``) bounds staleness as the corpus grows, and
    only non-abstained answers are stored — abstentions are exactly the queries a
    later ingestion might newly answer, so they are always recomputed.
    """

    __tablename__ = "answer_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
