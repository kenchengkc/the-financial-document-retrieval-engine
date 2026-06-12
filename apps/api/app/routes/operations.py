from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.schemas.operations import DataQualityReport
from apps.api.app.services.operations_service import build_data_quality_report

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/quality", response_model=DataQualityReport)
def data_quality(
    session: Annotated[Session, Depends(get_db_session)],
    stale_after_days: Annotated[int, Query(ge=30, le=730)] = 150,
) -> DataQualityReport:
    return build_data_quality_report(
        session,
        stale_after_days=stale_after_days,
    )
