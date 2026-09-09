from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.schemas.operations import DataQualityReport
from apps.api.app.schemas.retrieval_telemetry import RetrievalTelemetryResponse
from apps.api.app.services.operations_service import get_data_quality_report
from apps.api.app.services.retrieval_telemetry_service import get_retrieval_telemetry

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/quality", response_model=DataQualityReport)
def data_quality(
    session: Annotated[Session, Depends(get_db_session)],
) -> DataQualityReport:
    return get_data_quality_report(session)


@router.get("/retrieval-telemetry", response_model=RetrievalTelemetryResponse)
def retrieval_telemetry(
    session: Annotated[Session, Depends(get_db_session)],
    sample_limit: Annotated[int, Query(ge=50, le=5000)] = 1000,
) -> RetrievalTelemetryResponse:
    """Return content-free aggregates from separate latest-N retrieval and answer samples.

    This is not a fixed time-window or all-request metric. The endpoint independently selects the
    newest persisted retrieval runs and answer runs, up to ``sample_limit`` rows of each type.
    """

    return get_retrieval_telemetry(session, sample_limit=sample_limit)
