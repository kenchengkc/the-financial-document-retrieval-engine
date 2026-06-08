from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.schemas.companies import CompaniesResponse, CoverageResponse
from apps.api.app.services.companies_service import get_coverage, list_companies

router = APIRouter(tags=["companies"])


@router.get("/coverage", response_model=CoverageResponse)
def coverage(
    session: Annotated[Session, Depends(get_db_session)],
) -> CoverageResponse:
    return get_coverage(session)


@router.get("/companies", response_model=CompaniesResponse)
def companies(
    session: Annotated[Session, Depends(get_db_session)],
    indexed_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompaniesResponse:
    return list_companies(
        session,
        indexed_only=indexed_only,
        limit=limit,
        offset=offset,
    )
