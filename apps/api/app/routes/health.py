from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session


class HealthResponse(BaseModel):
    status: str


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process liveness probe; intentionally does not depend on external services."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def readiness(
    session: Annotated[Session, Depends(get_db_session)],
) -> HealthResponse:
    """Dependency readiness probe for traffic admission and operational diagnostics."""

    try:
        session.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(status_code=503, detail="database unavailable") from error
    return HealthResponse(status="ok")
