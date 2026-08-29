"""Typed experiment registry and fail-closed replay for the sealed OOS stack."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.oos_diagnostics import OOSDiagnosticsReport
from fdre.research.oos_implementation import OOSImplementationReport
from fdre.research.oos_promotion import OOSPromotionReport
from fdre.research.oos_selection import OOSSelectionSuiteReport
from fdre.research.walk_forward import WalkForwardStudyReport

ArtifactKind = Literal[
    "walk_forward",
    "oos_diagnostics",
    "oos_selection",
    "oos_implementation",
    "oos_promotion",
]
_REGISTRY_VERSION = "research-experiment-registry-v1"
_EXPECTED_EXPERIMENT_TYPES: dict[ArtifactKind, str] = {
    "walk_forward": "walk_forward_signal_study",
    "oos_diagnostics": "oos_signal_diagnostics",
    "oos_selection": "oos_signal_selection_suite",
    "oos_implementation": "oos_signal_implementation",
    "oos_promotion": "oos_signal_promotion",
}


class ResearchArtifactRef(BaseModel):
    kind: ArtifactKind
    experiment_key: str
    payload_sha256: str


class FilingLineageRef(BaseModel):
    ticker: str
    accession_number: str
    available_at: str
    max_source_available_at: str
    feature_lineage_id: str | None


class ResearchExperimentManifest(BaseModel):
    experiment_id: str
    registry_version: str = _REGISTRY_VERSION
    signal_name: str
    outcome_name: str
    signal_definition: dict[str, object] = Field(default_factory=dict)
    dataset_version: str
    feature_version: str
    market_data_version: str
    universe_snapshot_id: str
    feature_snapshot_id: str
    code_sha: str
    feature_lineage_digest: str | None
    fold_schedule: list[dict[str, object]]
    filing_lineage: list[FilingLineageRef]
    implementation_assumptions: dict[str, object]
    statistical_assumptions: dict[str, object]
    robustness_assumptions: dict[str, object]
    slice_snapshot_id: str
    artifacts: list[ResearchArtifactRef]
    final_decisions: list[dict[str, object]]


class ResearchReplayResult(BaseModel):
    experiment_id: str
    verified: bool
    artifact_count: int
    final_decisions: list[dict[str, object]]


def build_research_experiment_manifest(
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> ResearchExperimentManifest:
    """Bind every research layer and source identity into one immutable manifest."""
    _validate_chain(source, diagnostics, selection, implementation, promotion)
    reports: list[tuple[ArtifactKind, str, BaseModel]] = [
        ("walk_forward", source.experiment_key, source),
        ("oos_diagnostics", diagnostics.diagnostics_key, diagnostics),
        ("oos_selection", selection.selection_key, selection),
        ("oos_implementation", implementation.implementation_key, implementation),
        ("oos_promotion", promotion.promotion_key, promotion),
    ]
    artifacts = [
        ResearchArtifactRef(
            kind=kind,
            experiment_key=key,
            payload_sha256=_model_digest(report),
        )
        for kind, key, report in reports
    ]
    lineage = _filing_lineage(source)
    fold_schedule = [
        {
            "fold_id": fold.fold_id,
            "status": fold.status,
            "definition": fold.definition.model_dump(mode="json"),
            "train_accessions": fold.train_accessions,
            "validation_accessions": fold.validation_accessions,
            "purged_development_accessions": fold.purged_development_accessions,
            "test_accessions": fold.test_accessions,
        }
        for fold in source.folds
    ]
    payload: dict[str, Any] = {
        "registry_version": _REGISTRY_VERSION,
        "signal_name": source.signal_name,
        "outcome_name": source.outcome_name,
        "signal_definition": source.definition,
        "dataset_version": source.dataset_version,
        "feature_version": source.feature_version,
        "market_data_version": source.market_data_version,
        "universe_snapshot_id": source.universe_snapshot_id,
        "feature_snapshot_id": source.feature_snapshot_id,
        "code_sha": source.code_sha,
        "feature_lineage_digest": source.feature_lineage_digest,
        "fold_schedule": fold_schedule,
        "filing_lineage": [item.model_dump(mode="json") for item in lineage],
        "implementation_assumptions": implementation.config.model_dump(mode="json"),
        "statistical_assumptions": selection.config.model_dump(mode="json"),
        "robustness_assumptions": promotion.config.model_dump(mode="json"),
        "slice_snapshot_id": promotion.slice_snapshot_id,
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "final_decisions": [item.model_dump(mode="json") for item in promotion.decisions],
    }
    experiment_id = _stable_digest(payload)
    return ResearchExperimentManifest(experiment_id=experiment_id, **payload)


def persist_research_experiment_manifest(
    session: Session,
    manifest: ResearchExperimentManifest,
) -> ResearchExperiment:
    """Persist a content-addressed root manifest without allowing mutation in place."""
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == manifest.experiment_id
        )
    )
    payload = manifest.model_dump(mode="json")
    config_json = {
        "registry_version": manifest.registry_version,
        "artifact_keys": [item.experiment_key for item in manifest.artifacts],
        "slice_snapshot_id": manifest.slice_snapshot_id,
    }
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=manifest.experiment_id,
            experiment_type="research_experiment_manifest",
            dataset_version=manifest.dataset_version,
            feature_version=manifest.feature_version,
            code_sha=manifest.code_sha,
            config_json=config_json,
            results_json=payload,
        )
        session.add(experiment)
    else:
        if experiment.results_json != payload:
            raise ValueError("registered research experiment payload mismatch")
        return experiment
    session.commit()
    session.refresh(experiment)
    return experiment


def inspect_research_experiment(
    session: Session,
    experiment_id: str,
) -> ResearchExperimentManifest:
    row = _get_experiment(session, experiment_id)
    if row.experiment_type != "research_experiment_manifest":
        raise ValueError(f"{experiment_id} is not a research experiment manifest")
    return ResearchExperimentManifest.model_validate(row.results_json)


def verify_research_experiment(
    session: Session,
    experiment_id: str,
) -> ResearchExperimentManifest:
    """Verify manifest identity plus child type and exact persisted payload hashes."""
    manifest = inspect_research_experiment(session, experiment_id)
    if _manifest_identity(manifest) != manifest.experiment_id:
        raise ValueError("research experiment manifest digest mismatch")
    for artifact in manifest.artifacts:
        row = _get_experiment(session, artifact.experiment_key)
        expected_type = _EXPECTED_EXPERIMENT_TYPES[artifact.kind]
        if row.experiment_type != expected_type:
            raise ValueError(
                f"artifact type mismatch for {artifact.kind}:{artifact.experiment_key}"
            )
        actual = _json_digest(row.results_json)
        if actual != artifact.payload_sha256:
            raise ValueError(
                f"artifact digest mismatch for {artifact.kind}:{artifact.experiment_key}"
            )
    return manifest


def replay_research_experiment(
    session: Session,
    experiment_id: str,
) -> ResearchReplayResult:
    """Fail-closed replay from persisted immutable artifacts, without live refetches."""
    manifest = verify_research_experiment(session, experiment_id)
    promotion_ref = next(
        (item for item in manifest.artifacts if item.kind == "oos_promotion"),
        None,
    )
    if promotion_ref is None:
        raise ValueError("registered experiment has no OOS promotion artifact")
    promotion_row = _get_experiment(session, promotion_ref.experiment_key)
    promotion = OOSPromotionReport.model_validate(promotion_row.results_json)
    replayed_decisions = [item.model_dump(mode="json") for item in promotion.decisions]
    if replayed_decisions != manifest.final_decisions:
        raise ValueError("replayed final decisions differ from registered manifest")
    return ResearchReplayResult(
        experiment_id=manifest.experiment_id,
        verified=True,
        artifact_count=len(manifest.artifacts),
        final_decisions=replayed_decisions,
    )


def write_research_experiment_manifest(
    path: str | Path,
    manifest: ResearchExperimentManifest,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _validate_chain(
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    if not source.sealed_oos or not diagnostics.sealed_oos or not implementation.sealed_oos:
        raise ValueError("registry accepts only sealed OOS research artifacts")
    if diagnostics.source_experiment_key != source.experiment_key:
        raise ValueError("diagnostics source experiment mismatch")
    if any(
        item.source_experiment_key != source.experiment_key
        for item in selection.decisions
    ):
        raise ValueError("selection suite contains a foreign source experiment")
    if implementation.source_experiment_key != source.experiment_key:
        raise ValueError("implementation source experiment mismatch")
    if implementation.source_selection_key != selection.selection_key:
        raise ValueError("implementation selection key mismatch")
    if promotion.source_experiment_key != source.experiment_key:
        raise ValueError("promotion source experiment mismatch")
    if promotion.source_diagnostics_key != diagnostics.diagnostics_key:
        raise ValueError("promotion diagnostics key mismatch")
    if promotion.source_selection_key != selection.selection_key:
        raise ValueError("promotion selection key mismatch")
    if promotion.source_implementation_key != implementation.implementation_key:
        raise ValueError("promotion implementation key mismatch")


def _filing_lineage(source: WalkForwardStudyReport) -> list[FilingLineageRef]:
    unique: dict[str, FilingLineageRef] = {}
    for item in source.oos_observations:
        lineage = FilingLineageRef(
            ticker=item.ticker.upper(),
            accession_number=item.accession_number,
            available_at=item.available_at.isoformat(),
            max_source_available_at=item.max_source_available_at.isoformat(),
            feature_lineage_id=item.feature_lineage_id,
        )
        existing = unique.get(item.accession_number)
        if existing is not None and existing != lineage:
            raise ValueError(
                f"conflicting filing lineage for accession {item.accession_number}"
            )
        unique[item.accession_number] = lineage
    return sorted(
        unique.values(),
        key=lambda item: (item.accession_number, item.available_at),
    )


def _manifest_identity(manifest: ResearchExperimentManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"experiment_id"})
    return _stable_digest(payload)


def _get_experiment(session: Session, experiment_key: str) -> ResearchExperiment:
    row = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == experiment_key
        )
    )
    if row is None:
        raise ValueError(f"missing research experiment artifact {experiment_key}")
    return row


def _model_digest(model: BaseModel) -> str:
    return _json_digest(model.model_dump(mode="json"))


def _json_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stable_digest(payload: object) -> str:
    return _json_digest(payload)
