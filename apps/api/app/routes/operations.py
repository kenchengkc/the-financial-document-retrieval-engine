from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.schemas.operations import DataQualityReport
from apps.api.app.services.operations_service import get_data_quality_report

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/quality", response_model=DataQualityReport)
def data_quality(
    session: Annotated[Session, Depends(get_db_session)],
) -> DataQualityReport:
    return get_data_quality_report(session)
