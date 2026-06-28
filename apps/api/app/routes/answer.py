from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.schemas.answer import AnswerRequest, AnswerResponse
from apps.api.app.services.answer_cache import (
    answer_cache_key,
    get_cached_answer,
    store_cached_answer,
)
from apps.api.app.services.answer_service import answer_question

router = APIRouter(tags=["answer"])


@router.post("/answer", response_model=AnswerResponse)
def answer(
    request: AnswerRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> AnswerResponse:
    ttl = settings.answer_cache_ttl_seconds
    key = answer_cache_key(request.question, settings)
    cached = get_cached_answer(session, key, ttl)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached
    result = AnswerResponse.model_validate(
        answer_question(session, settings, question=request.question),
        from_attributes=True,
    )
    store_cached_answer(session, key, result, ttl)
    response.headers["X-Cache"] = "MISS"
    return result
