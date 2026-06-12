from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from fdre.research.filing_diffs import FilingDifference, compare_filing_to_prior

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/filing-differences/{accession_number}", response_model=FilingDifference)
def filing_differences(
    accession_number: str,
    session: Annotated[Session, Depends(get_db_session)],
    as_of: Annotated[datetime | None, Query()] = None,
) -> FilingDifference:
    try:
        return compare_filing_to_prior(session, accession_number, as_of=as_of)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
