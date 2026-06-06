from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.schemas.search import SearchRequest, SearchResponse
from apps.api.app.services.retrieval_service import search_documents

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    result = search_documents(
        session,
        settings,
        query=request.query,
        filters=request.filters,
        top_k=request.top_k,
    )
    return SearchResponse(
        query=request.query,
        rewritten_queries=result.preprocessed.rewritten_queries,
        filters=result.preprocessed.filters,
        results=result.candidates,
        latency_ms=result.latency_ms,
    )
