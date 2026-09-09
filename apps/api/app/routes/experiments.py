from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.models import ResearchExperiment
from apps.api.app.schemas.research_experiments import (
    ResearchExperimentListResponse,
    ResearchExperimentSummary,
)
from fdre.research.experiments.registry import (
    ResearchExperimentBundle,
    ResearchExperimentManifest,
    ResearchReplayResult,
    build_research_experiment_bundle,
    inspect_research_experiment,
    replay_research_experiment,
)

router = APIRouter(prefix="/research/experiments", tags=["research"])
ExperimentId = Annotated[
    str,
    Path(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


@router.get("", response_model=ResearchExperimentListResponse)
def research_experiments(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ResearchExperimentListResponse:
    rows = list(
        session.scalars(
            select(ResearchExperiment)
            .where(ResearchExperiment.experiment_type == "research_experiment_manifest")
            .order_by(ResearchExperiment.created_at.desc(), ResearchExperiment.id.desc())
            .limit(limit)
        )
    )
    summaries: list[ResearchExperimentSummary] = []
    for row in rows:
        try:
            manifest = ResearchExperimentManifest.model_validate(row.results_json)
        except ValidationError as error:
            raise HTTPException(
                status_code=409,
                detail=f"registered research manifest is malformed: {row.experiment_key}",
            ) from error
        summaries.append(
            ResearchExperimentSummary(
                experiment_id=manifest.experiment_id,
                signal_name=manifest.signal_name,
                outcome_name=manifest.outcome_name,
                dataset_version=manifest.dataset_version,
                feature_version=manifest.feature_version,
                market_data_version=manifest.market_data_version,
                universe_snapshot_id=manifest.universe_snapshot_id,
                feature_snapshot_id=manifest.feature_snapshot_id,
                code_sha=manifest.code_sha,
                feature_lineage_digest=manifest.feature_lineage_digest,
                slice_snapshot_id=manifest.slice_snapshot_id,
                artifact_count=len(manifest.artifacts),
                filing_lineage_count=len(manifest.filing_lineage),
                final_decisions=manifest.final_decisions,
                registered_at=row.created_at,
            )
        )
    return ResearchExperimentListResponse(experiments=summaries)


@router.get("/{experiment_id}", response_model=ResearchExperimentManifest)
def research_experiment(
    experiment_id: ExperimentId,
    session: Annotated[Session, Depends(get_db_session)],
) -> ResearchExperimentManifest:
    try:
        return inspect_research_experiment(session, experiment_id)
    except ValueError as error:
        raise _registry_http_error(error) from error


@router.get("/{experiment_id}/verify", response_model=ResearchReplayResult)
def verify_research_experiment_endpoint(
    experiment_id: ExperimentId,
    session: Annotated[Session, Depends(get_db_session)],
) -> ResearchReplayResult:
    try:
        return replay_research_experiment(session, experiment_id)
    except ValueError as error:
        raise _registry_http_error(error) from error


@router.get("/{experiment_id}/bundle", response_model=ResearchExperimentBundle)
def research_experiment_bundle(
    experiment_id: ExperimentId,
    session: Annotated[Session, Depends(get_db_session)],
) -> ResearchExperimentBundle:
    """Export the verified immutable root and child artifacts for offline verification."""

    try:
        return build_research_experiment_bundle(session, experiment_id)
    except ValueError as error:
        raise _registry_http_error(error) from error


def _registry_http_error(error: ValueError) -> HTTPException:
    detail = str(error)
    status_code = 404 if detail.startswith("missing research experiment artifact") else 409
    return HTTPException(status_code=status_code, detail=detail)
