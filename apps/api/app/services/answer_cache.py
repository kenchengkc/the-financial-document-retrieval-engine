"""Point-in-time-aware cache for ``/answer`` responses.

The answer pipeline is deterministic for a given question and corpus, so an
identical question can be served from a stored response instead of re-running
retrieval + rerank + generation. Safety comes from three places:

* the key includes a pipeline-config version, so any model/threshold change
  produces a fresh namespace rather than serving an answer from old settings;
* a TTL bounds staleness while the corpus is still being deepened;
* abstentions are never cached — those are precisely the questions a later
  ingestion might newly be able to answer, so they always recompute.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import AnswerCache
from apps.api.app.schemas.answer import AnswerResponse

# Bump when the answer pipeline logic changes in a way that should invalidate
# previously cached answers but isn't captured by a settings value below.
_PIPELINE_VERSION = "1"


def answer_cache_key(question: str, settings: Settings) -> str:
    """Stable key for (question, pipeline configuration)."""
    normalized = " ".join(question.split())
    version = "|".join(
        str(part)
        for part in (
            _PIPELINE_VERSION,
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.sparse_provider,
            settings.reranker_provider,
            settings.reranker_model,
            settings.rerank_top_n,
            settings.min_rerank_score,
            settings.answer_generator,
            settings.answer_top_k,
            settings.min_evidence_chunks,
            settings.min_retrieval_score,
            settings.neighbor_expansion_window,
        )
    )
    return hashlib.sha256(f"{version}\n{normalized}".encode()).hexdigest()


def get_cached_answer(
    session: Session, key: str, ttl_seconds: int
) -> AnswerResponse | None:
    if ttl_seconds <= 0:
        return None
    row = session.get(AnswerCache, key)
    if row is None:
        return None
    if datetime.now(UTC) - _as_aware(row.created_at) > timedelta(seconds=ttl_seconds):
        return None
    return AnswerResponse.model_validate(row.response_json)


def store_cached_answer(
    session: Session, key: str, response: AnswerResponse, ttl_seconds: int
) -> None:
    if ttl_seconds <= 0 or response.abstained:
        return
    session.merge(
        AnswerCache(
            cache_key=key,
            response_json=response.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    session.commit()


def _as_aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat stored timestamps as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
