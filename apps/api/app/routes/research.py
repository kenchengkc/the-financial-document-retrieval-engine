from __future__ import annotations

from datetime import date, datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.models import ResearchExperiment
from apps.api.app.services.research_cache import (
    PANEL_CACHE_PREFIX,
    THEMATIC_CACHE_PREFIX,
    read_cached_model,
    research_cache_key,
    write_cached_model,
)
from apps.api.app.services.retrieval_service import search_documents
from apps.api.app.services.signal_validation import enrich_signal_study_payloads
from fdre.research.filing_diffs import FilingDifference, compare_filing_to_prior
from fdre.research.financial_facts import (
    CanonicalMetric,
    FinancialFactQuery,
    FinancialFactsResponse,
    query_financial_facts,
)
from fdre.research.panel import (
    FEATURE_VERSION,
    ResearchPanel,
    ResearchPanelQuery,
    build_research_panel,
    serialize_research_panel,
)
from fdre.research.screen import (
    ResearchScreenPlan,
    ResearchScreenResponse,
    execute_research_screen,
)
from fdre.research.thematic import (
    ThematicScanRequest,
    ThematicScanResponse,
    diversify_candidates_by_issuer,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters

router = APIRouter(prefix="/research", tags=["research"])

_CACHEABLE_THEMATIC_QUERIES = frozenset(
    {
        "foreign exchange and currency headwinds",
        "generative ai investment and risk",
        "data center capacity constraints",
    }
)


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
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    tickers: Annotated[list[str] | None, Query()] = None,
    period_end_from: Annotated[date | None, Query()] = None,
    period_end_to: Annotated[date | None, Query()] = None,
    as_of: Annotated[datetime | None, Query()] = None,
    form_types: Annotated[list[str] | None, Query()] = None,
    sections: Annotated[list[str] | None, Query()] = None,
    include_amendments: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
) -> ResearchPanel:
    query = ResearchPanelQuery(
        tickers=tickers or [],
        period_end_from=period_end_from,
        period_end_to=period_end_to,
        as_of=as_of,
        form_types=form_types or ["10-K", "10-Q"],
        sections=sections or [],
        include_amendments=include_amendments,
        limit=limit,
    )
    cache_key = research_cache_key(
        PANEL_CACHE_PREFIX,
        {"feature_version": FEATURE_VERSION, "query": query.model_dump(mode="json")},
    )
    cached = read_cached_model(
        session,
        cache_key=cache_key,
        ttl_seconds=settings.research_cache_ttl_seconds,
        model_type=ResearchPanel,
    )
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached
    panel = build_research_panel(session, query)
    if settings.research_cache_ttl_seconds > 0:
        write_cached_model(
            session,
            cache_key=cache_key,
            prefix=PANEL_CACHE_PREFIX,
            value=panel,
        )
        response.headers["X-Cache"] = "MISS"
    else:
        response.headers["X-Cache"] = "BYPASS"
    return panel


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


@router.post("/screen", response_model=ResearchScreenResponse)
def research_screen(
    request: ResearchScreenPlan,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResearchScreenResponse:
    started = perf_counter()

    def semantic_search(
        query: str,
        filters: SearchFilters,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        return search_documents(
            session,
            settings,
            query=query,
            filters=filters,
            top_k=top_k,
        ).candidates

    try:
        result = execute_research_screen(
            session,
            request,
            semantic_search=semantic_search,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return result.model_copy(
        update={"latency_ms": round((perf_counter() - started) * 1000)}
    )


@router.get("/signal-study")
def signal_study(
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    payloads = _published_signal_study_payloads(session)
    if not payloads:
        raise HTTPException(status_code=404, detail="No signal study has been published yet.")
    return payloads[0]


@router.get("/signal-studies")
def signal_studies(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> dict[str, Any]:
    return {"studies": _published_signal_study_payloads(session)[:limit]}


def _published_signal_study_payloads(session: Session) -> list[dict[str, Any]]:
    experiments = list(
        session.scalars(
            select(ResearchExperiment)
            .where(ResearchExperiment.experiment_type == "signal_study")
            .order_by(ResearchExperiment.created_at.desc(), ResearchExperiment.id.desc())
            .limit(200)
        )
    )
    # Dedupe to one study per (signal, outcome). The newest feature methodology
    # supersedes an older definition; within that methodology, retain the run
    # with the broadest market-data coverage.
    best: dict[tuple[str, str], ResearchExperiment] = {}
    current_versions: dict[tuple[str, str], str] = {}
    for experiment in experiments:
        report = experiment.results_json or {}
        key = (
            str(report.get("signal_name", "")),
            str(report.get("outcome_name", "abnormal_return")),
        )
        incumbent = best.get(key)
        version = str(report.get("feature_version") or experiment.feature_version)
        if incumbent is None:
            best[key] = experiment
            current_versions[key] = version
        elif version == current_versions[key] and int(
            report.get("event_count", 0) or 0
        ) > int(
            (incumbent.results_json or {}).get("event_count", 0) or 0
        ):
            best[key] = experiment
    ordered = sorted(
        best.values(),
        key=lambda experiment: (experiment.created_at, experiment.id),
        reverse=True,
    )
    return enrich_signal_study_payloads(
        [_signal_study_payload(experiment) for experiment in ordered]
    )


def _signal_study_payload(experiment: ResearchExperiment) -> dict[str, Any]:
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
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ThematicScanResponse:
    normalized_query = " ".join(request.query.casefold().split())
    cache_key = research_cache_key(
        THEMATIC_CACHE_PREFIX,
        {
            "request": request.model_dump(mode="json"),
            "embedding": [
                settings.embedding_provider,
                settings.embedding_model,
                settings.embedding_dimensions,
            ],
            "reranker": [
                settings.reranker_provider,
                settings.reranker_model,
                settings.rerank_top_n,
            ],
        },
    )
    cacheable = normalized_query in _CACHEABLE_THEMATIC_QUERIES
    if cacheable:
        cached = read_cached_model(
            session,
            cache_key=cache_key,
            ttl_seconds=settings.research_cache_ttl_seconds,
            model_type=ThematicScanResponse,
        )
        if cached is not None:
            response.headers["X-Cache"] = "HIT"
            return cached.model_copy(update={"latency_ms": 0})
    result = search_documents(
        session,
        settings,
        query=request.query,
        filters=request.filters,
        top_k=min(100, request.issuers * request.results_per_issuer * 2),
    )
    issuers = diversify_candidates_by_issuer(
        result.candidates,
        issuer_limit=request.issuers,
        results_per_issuer=request.results_per_issuer,
    )
    scan = ThematicScanResponse(
        query=request.query,
        filters=result.preprocessed.filters,
        issuer_count=len(issuers),
        issuers=issuers,
        latency_ms=result.latency_ms,
    )
    if cacheable and settings.research_cache_ttl_seconds > 0:
        write_cached_model(
            session,
            cache_key=cache_key,
            prefix=THEMATIC_CACHE_PREFIX,
            value=scan,
        )
        response.headers["X-Cache"] = "MISS"
    else:
        response.headers["X-Cache"] = "BYPASS"
    return scan
