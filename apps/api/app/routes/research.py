from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models import ResearchExperiment
from apps.api.app.services.retrieval_service import search_documents
from fdre.research.filing_diffs import FilingDifference, compare_filing_to_prior
from fdre.research.financial_facts import (
    CanonicalMetric,
    FinancialFactQuery,
    FinancialFactsResponse,
    query_financial_facts,
)
from fdre.research.panel import (
    ResearchPanel,
    ResearchPanelQuery,
    build_research_panel,
    serialize_research_panel,
)
from fdre.research.thematic import (
    ThematicScanRequest,
    ThematicScanResponse,
    diversify_candidates_by_issuer,
)

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


@router.get("/panel/export")
def export_research_panel(
    session: Annotated[Session, Depends(get_db_session)],
    tickers: Annotated[list[str] | None, Query()] = None,
    period_end_from: Annotated[date | None, Query()] = None,
    period_end_to: Annotated[date | None, Query()] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    form_types: Annotated[list[str] | None, Query()] = None,
    sections: Annotated[list[str] | None, Query()] = None,
    include_amendments: Annotated[bool, Query()] = False,
    output_format: Annotated[Literal["json", "csv", "parquet"], Query()] = "parquet",
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1000,
) -> Response:
    panel = build_research_panel(
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
    try:
        content, media_type = serialize_research_panel(
            panel,
            output_format=output_format,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=501, detail=str(error)) from error
    extension = "parquet" if output_format == "parquet" else output_format
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="fdre-panel-{panel.corpus_snapshot_id}.{extension}"'
            )
        },
    )


@router.get("/signal-study")
def signal_study(
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    experiment = session.scalar(
        select(ResearchExperiment)
        .where(ResearchExperiment.experiment_type == "signal_study")
        .order_by(ResearchExperiment.created_at.desc(), ResearchExperiment.id.desc())
        .limit(1)
    )
    if experiment is None:
        raise HTTPException(status_code=404, detail="No signal study has been published yet.")
    return {
        "experiment_id": experiment.id,
        "experiment_key": experiment.experiment_key,
        "code_sha": experiment.code_sha,
        "created_at": experiment.created_at.isoformat(),
        "report": experiment.results_json,
    }


@router.post("/thematic-scan", response_model=ThematicScanResponse)
def thematic_scan(
    request: ThematicScanRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ThematicScanResponse:
    result = search_documents(
        session,
        settings,
        query=request.query,
        filters=request.filters,
        top_k=min(100, request.issuers * request.results_per_issuer * 4),
    )
    issuers = diversify_candidates_by_issuer(
        result.candidates,
        issuer_limit=request.issuers,
        results_per_issuer=request.results_per_issuer,
    )
    return ThematicScanResponse(
        query=request.query,
        filters=result.preprocessed.filters,
        issuer_count=len(issuers),
        issuers=issuers,
        latency_ms=result.latency_ms,
    )
