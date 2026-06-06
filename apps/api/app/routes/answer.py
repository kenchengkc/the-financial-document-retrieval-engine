from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.schemas.answer import AnswerRequest, AnswerResponse
from apps.api.app.services.answer_service import answer_question

router = APIRouter(tags=["answer"])


@router.post("/answer", response_model=AnswerResponse)
def answer(
    request: AnswerRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerResponse:
    return AnswerResponse.model_validate(
        answer_question(
            session,
            settings,
            question=request.question,
        ),
        from_attributes=True,
    )
