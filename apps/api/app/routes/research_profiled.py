from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import get_db_session
from apps.api.app.services.retrieval_service import search_documents
from fdre.research.screen import (
    ResearchScreenPlan,
    ResearchScreenResponse,
    execute_research_screen,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters

router = APIRouter(prefix="/research", tags=["research-profile"])


@router.post(
    "/screen",
    response_model=ResearchScreenResponse,
    include_in_schema=False,
)
def profiled_research_screen(
    request: ResearchScreenPlan,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResearchScreenResponse:
    """Temporary production profiler for the existing research-screen contract.

    This route intentionally preserves the normal screen response and ranking semantics.
    It only adds timing headers so the deployed Railway path can be decomposed without
    requiring access to platform logs. It is registered before the normal research
    router while profiling is active and should be removed after the bottleneck is
    measured and optimized.
    """

    started = perf_counter()
    search_wall_ms = 0
    search_stages: dict[str, int] = {}
    screen_stages: dict[str, int] = {}

    def semantic_search(
        query: str,
        filters: SearchFilters,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        nonlocal search_wall_ms
        search_started = perf_counter()
        result = search_documents(
            session,
            settings,
            query=query,
            filters=filters,
            top_k=top_k,
        )
        search_wall_ms = round((perf_counter() - search_started) * 1000)
        search_stages.update(result.stage_timings_ms)
        return result.candidates

    try:
        result = execute_research_screen(
            session,
            request,
            semantic_search=semantic_search,
            timings_ms=screen_stages,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    total_ms = round((perf_counter() - started) * 1000)
    nonsearch_ms = max(total_ms - search_wall_ms, 0)
    response.headers["X-FDRE-Screen-Ms"] = str(total_ms)
    response.headers["X-FDRE-Semantic-Search-Ms"] = str(search_wall_ms)
    response.headers["X-FDRE-Nonsearch-Ms"] = str(nonsearch_ms)

    if search_stages:
        response.headers["Server-Timing"] = ", ".join(
            [
                f"preprocess;dur={search_stages.get('preprocess', 0)}",
                f"provider_init;dur={search_stages.get('provider_init', 0)}",
                f"embedding;dur={search_stages.get('embedding', 0)}",
                f"dense;dur={search_stages.get('dense', 0)}",
                f"sparse;dur={search_stages.get('sparse', 0)}",
                f"fusion;dur={search_stages.get('fusion', 0)}",
                f"rerank;dur={search_stages.get('rerank', 0)}",
                f"audit_persist;dur={search_stages.get('audit_persist', 0)}",
                f"semantic_search;dur={search_wall_ms}",
                f"panel_document_select;dur={screen_stages.get('panel_document_select', 0)}",
                f"panel_history_pool;dur={screen_stages.get('panel_history_pool', 0)}",
                f"panel_prior_resolution;dur={screen_stages.get('panel_prior_resolution', 0)}",
                f"panel_snapshot;dur={screen_stages.get('panel_snapshot', 0)}",
                f"panel_element_load;dur={screen_stages.get('panel_element_load', 0)}",
                f"panel_fact_load;dur={screen_stages.get('panel_fact_load', 0)}",
                f"panel_row_build;dur={screen_stages.get('panel_row_build', 0)}",
                f"panel_build;dur={screen_stages.get('panel_build', 0)}",
                f"latest_selection;dur={screen_stages.get('latest_selection', 0)}",
                f"condition_eval;dur={screen_stages.get('condition_eval', 0)}",
                f"evidence_hydration;dur={screen_stages.get('evidence_hydration', 0)}",
                f"row_materialization;dur={screen_stages.get('row_materialization', 0)}",
                f"lineage_validation;dur={screen_stages.get('lineage_validation', 0)}",
                f"manifest_build;dur={screen_stages.get('manifest_build', 0)}",
                f"nonsearch;dur={nonsearch_ms}",
                f"screen;dur={total_ms}",
            ]
        )
    else:
        response.headers["Server-Timing"] = (
            f"nonsearch;dur={nonsearch_ms}, screen;dur={total_ms}"
        )

    return result.model_copy(update={"latency_ms": total_ms})
