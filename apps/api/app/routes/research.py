from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from fdre.research.filing_diffs import FilingDifference, compare_filing_to_prior
from fdre.research.financial_facts import (
    CanonicalMetric,
    FinancialFactQuery,
    FinancialFactsResponse,
    query_financial_facts,
)
from fdre.research.panel import ResearchPanel, ResearchPanelQuery, build_research_panel

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


@router.get("/facts", response_model=FinancialFactsResponse)
def financial_facts(
    session: Annotated[Session, Depends(get_db_session)],
    tickers: Annotated[list[str] | None, Query()] = None,
    metrics: Annotated[list[CanonicalMetric] | None, Query()] = None,
    period_end_from: Annotated[date | None, Query()] = None,
    period_end_to: Annotated[date | None, Query()] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    form_types: Annotated[list[str] | None, Query()] = None,
    restatement_policy: Annotated[
        Literal["latest", "as_reported", "all"],
        Query(),
    ] = "latest",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> FinancialFactsResponse:
    return query_financial_facts(
        session,
        FinancialFactQuery(
            tickers=tickers or [],
            metrics=metrics or [],
            period_end_from=period_end_from,
            period_end_to=period_end_to,
            as_of=as_of,
            form_types=form_types or [],
            restatement_policy=restatement_policy,
            limit=limit,
        ),
    )


@router.get("/panel", response_model=ResearchPanel)
def research_panel(
    session: Annotated[Session, Depends(get_db_session)],
    tickers: Annotated[list[str] | None, Query()] = None,
    period_end_from: Annotated[date | None, Query()] = None,
    period_end_to: Annotated[date | None, Query()] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    form_types: Annotated[list[str] | None, Query()] = None,
    sections: Annotated[list[str] | None, Query()] = None,
    include_amendments: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1000,
) -> ResearchPanel:
    return build_research_panel(
        session,
        ResearchPanelQuery(
            tickers=tickers or [],
            period_end_from=period_end_from,
            period_end_to=period_end_to,
            as_of=as_of,
            form_types=form_types or ["10-K", "10-Q"],
            sections=sections or [],
            include_amendments=include_amendments,
            limit=limit,
        ),
    )
