from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ResearchExperimentSummary(BaseModel):
    experiment_id: str
    signal_name: str
    outcome_name: str
    dataset_version: str
    feature_version: str
    market_data_version: str
    universe_snapshot_id: str
    feature_snapshot_id: str
    code_sha: str
    feature_lineage_digest: str | None
    slice_snapshot_id: str
    artifact_count: int
    filing_lineage_count: int
    final_decisions: list[dict[str, object]] = Field(default_factory=list)
    registered_at: datetime


class ResearchExperimentListResponse(BaseModel):
    experiments: list[ResearchExperimentSummary]
