"""Typed experiment registry, fail-closed replay, and portable research bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiments.feature_replay import (
    RiskChurnFeatureReplayInput,
    replay_risk_churn_feature_input,
)
from fdre.research.experiments.replay_input import (
    WalkForwardReplayInput,
    replay_walk_forward_input,
)
from fdre.research.experiments.walk_forward import WalkForwardStudyReport
from fdre.research.oos.diagnostics import OOSDiagnosticsReport, build_oos_diagnostics
from fdre.research.oos.implementation import (
    OOSImplementationReport,
    evaluate_oos_implementation,
)
from fdre.research.oos.promotion import OOSPromotionReport, evaluate_oos_promotion
from fdre.research.oos.selection import (
    OOSSelectionSuiteReport,
    evaluate_oos_selection_suite,
)

ArtifactKind = Literal[
    "feature_input",
    "walk_forward_input",
    "walk_forward",
    "oos_diagnostics",
    "oos_selection",
    "oos_implementation",
    "oos_promotion",
]
ReplayMode = Literal[
    "artifact_verification",
    "downstream_computational_replay",
    "walk_forward_computational_replay",
    "feature_computational_replay",
]
_REGISTRY_VERSION_V1 = "research-experiment-registry-v1"
_REGISTRY_VERSION_V2 = "research-experiment-registry-v2"
_REGISTRY_VERSION_V3 = "research-experiment-registry-v3"
_REGISTRY_VERSION = "research-experiment-registry-v4"
_BUNDLE_VERSION = "research-experiment-bundle-v1"
_EXPECTED_EXPERIMENT_TYPES: dict[ArtifactKind, str] = {
    "feature_input": "risk_churn_feature_replay_input",
    "walk_forward_input": "walk_forward_replay_input",
    "walk_forward": "walk_forward_signal_study",
    "oos_diagnostics": "oos_signal_diagnostics",
    "oos_selection": "oos_signal_selection_suite",
    "oos_implementation": "oos_signal_implementation",
    "oos_promotion": "oos_signal_promotion",
}
_EXPECTED_ARTIFACT_MODELS: dict[ArtifactKind, type[BaseModel]] = {
    "feature_input": RiskChurnFeatureReplayInput,
    "walk_forward_input": WalkForwardReplayInput,
    "walk_forward": WalkForwardStudyReport,
    "oos_diagnostics": OOSDiagnosticsReport,
    "oos_selection": OOSSelectionSuiteReport,
    "oos_implementation": OOSImplementationReport,
    "oos_promotion": OOSPromotionReport,
}
_BASE_ARTIFACTS: list[ArtifactKind] = [
    "walk_forward",
    "oos_diagnostics",
    "oos_selection",
    "oos_implementation",
    "oos_promotion",
]
_RECOMPUTED_DOWNSTREAM: list[ArtifactKind] = [
    "oos_diagnostics",
    "oos_selection",
    "oos_implementation",
    "oos_promotion",
]


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
    promotion_slices: dict[str, list[str]] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    artifacts: list[ResearchArtifactRef]
    final_decisions: list[dict[str, object]]


class ResearchReplayResult(BaseModel):
    experiment_id: str
    verified: bool
    artifact_count: int
    replay_mode: ReplayMode = "artifact_verification"
    recomputed_artifacts: list[ArtifactKind] = Field(default_factory=list)
    final_decisions: list[dict[str, object]]


class ResearchBundleArtifact(BaseModel):
    kind: ArtifactKind
    experiment_key: str
    experiment_type: str
    payload_sha256: str
    payload: dict[str, Any]


class ResearchExperimentBundle(BaseModel):
    """Deterministic offline-verifiable package of one registered research root."""

    bundle_version: str = _BUNDLE_VERSION
    experiment_id: str
    manifest: ResearchExperimentManifest
    artifacts: list[ResearchBundleArtifact]
    bundle_sha256: str


def build_research_experiment_manifest(
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
    *,
    promotion_slices: dict[str, set[str]] | None = None,
    walk_forward_input: WalkForwardReplayInput | None = None,
    feature_input: RiskChurnFeatureReplayInput | None = None,
) -> ResearchExperimentManifest:
    """Bind every research layer and source identity into one immutable manifest."""
    _validate_chain(source, diagnostics, selection, implementation, promotion)
    normalized_slices = (
        _normalize_promotion_slices(promotion_slices)
        if promotion_slices is not None
        else None
    )
    if walk_forward_input is not None and normalized_slices is None:
        raise ValueError("walk-forward computational replay requires promotion slices")
    if feature_input is not None and walk_forward_input is None:
        raise ValueError("feature computational replay requires a walk-forward replay input")
    if feature_input is not None:
        registry_version = _REGISTRY_VERSION
    elif walk_forward_input is not None:
        registry_version = _REGISTRY_VERSION_V3
    elif normalized_slices is not None:
        registry_version = _REGISTRY_VERSION_V2
    else:
        registry_version = _REGISTRY_VERSION_V1

    if normalized_slices is not None:
        if selection.input_diagnostics_keys != [diagnostics.diagnostics_key]:
            raise ValueError(
                "computational replay requires exactly one registered diagnostics input"
            )
        if _stable_digest(normalized_slices) != promotion.slice_snapshot_id:
            raise ValueError("promotion slice memberships do not match slice snapshot id")
    if walk_forward_input is not None:
        _validate_walk_forward_input_binding(source, walk_forward_input)
    if feature_input is not None and walk_forward_input is not None:
        _validate_feature_input_binding(feature_input, walk_forward_input)

    reports: list[tuple[ArtifactKind, str, BaseModel]] = []
    if feature_input is not None:
        reports.append(("feature_input", feature_input.input_key, feature_input))
    if walk_forward_input is not None:
        reports.append(
            ("walk_forward_input", walk_forward_input.input_key, walk_forward_input)
        )
    reports.extend(
        [
            ("walk_forward", source.experiment_key, source),
            ("oos_diagnostics", diagnostics.diagnostics_key, diagnostics),
            ("oos_selection", selection.selection_key, selection),
            ("oos_implementation", implementation.implementation_key, implementation),
            ("oos_promotion", promotion.promotion_key, promotion),
        ]
    )
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
        "registry_version": registry_version,
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
    if normalized_slices is not None:
        payload["promotion_slices"] = normalized_slices
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
    payload = _manifest_storage_payload(manifest)
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
    _validate_manifest_version(manifest)
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
    """Replay a registered experiment without live data or provider refetches."""
    manifest = verify_research_experiment(session, experiment_id)
    payloads = {
        artifact.kind: dict(_get_experiment(session, artifact.experiment_key).results_json)
        for artifact in manifest.artifacts
    }
    return _replay_artifact_chain(manifest, payloads)


def build_research_experiment_bundle(
    session: Session,
    experiment_id: str,
) -> ResearchExperimentBundle:
    """Materialize a deterministic bundle after verifying the persisted registry chain."""

    manifest = verify_research_experiment(session, experiment_id)
    artifacts: list[ResearchBundleArtifact] = []
    for reference in manifest.artifacts:
        row = _get_experiment(session, reference.experiment_key)
        artifacts.append(
            ResearchBundleArtifact(
                kind=reference.kind,
                experiment_key=reference.experiment_key,
                experiment_type=row.experiment_type,
                payload_sha256=reference.payload_sha256,
                payload=dict(row.results_json),
            )
        )
    payload: dict[str, Any] = {
        "bundle_version": _BUNDLE_VERSION,
        "experiment_id": manifest.experiment_id,
        "manifest": _manifest_storage_payload(manifest),
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
    }
    return ResearchExperimentBundle(
        **payload,
        bundle_sha256=_stable_digest(payload),
    )


def verify_research_experiment_bundle(
    bundle: ResearchExperimentBundle,
    *,
    expected_experiment_id: str | None = None,
) -> ResearchReplayResult:
    """Verify and computationally replay a portable offline bundle when supported."""

    if expected_experiment_id is not None and bundle.experiment_id != expected_experiment_id:
        raise ValueError("research experiment bundle root does not match expected experiment id")
    _validate_manifest_version(bundle.manifest)
    if bundle.bundle_sha256 != _bundle_identity(bundle):
        raise ValueError("research experiment bundle digest mismatch")
    if bundle.experiment_id != bundle.manifest.experiment_id:
        raise ValueError("research experiment bundle manifest id mismatch")
    if _manifest_identity(bundle.manifest) != bundle.experiment_id:
        raise ValueError("research experiment bundle manifest digest mismatch")
    if len(bundle.artifacts) != len(bundle.manifest.artifacts):
        raise ValueError("research experiment bundle artifact count mismatch")

    payloads: dict[ArtifactKind, dict[str, Any]] = {}
    for reference, artifact in zip(bundle.manifest.artifacts, bundle.artifacts, strict=True):
        if (
            artifact.kind != reference.kind
            or artifact.experiment_key != reference.experiment_key
            or artifact.payload_sha256 != reference.payload_sha256
        ):
            raise ValueError(
                f"research experiment bundle artifact reference mismatch for {reference.kind}"
            )
        expected_type = _EXPECTED_EXPERIMENT_TYPES[reference.kind]
        if artifact.experiment_type != expected_type:
            raise ValueError(
                f"research experiment bundle artifact type mismatch for {reference.kind}"
            )
        if _json_digest(artifact.payload) != reference.payload_sha256:
            raise ValueError(
                f"research experiment bundle artifact digest mismatch for {reference.kind}"
            )
        _EXPECTED_ARTIFACT_MODELS[reference.kind].model_validate(artifact.payload)
        payloads[artifact.kind] = artifact.payload

    return _replay_artifact_chain(bundle.manifest, payloads)


def write_research_experiment_manifest(
    path: str | Path,
    manifest: ResearchExperimentManifest,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_manifest_storage_payload(manifest), indent=2, sort_keys=True) + "\n"
    )
    return destination


def write_research_experiment_bundle(
    path: str | Path,
    bundle: ResearchExperimentBundle,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def read_research_experiment_bundle(path: str | Path) -> ResearchExperimentBundle:
    return ResearchExperimentBundle.model_validate_json(Path(path).read_text())


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


def _validate_feature_input_binding(
    feature_input: RiskChurnFeatureReplayInput,
    walk_forward_input: WalkForwardReplayInput,
) -> None:
    if feature_input.signal_name != walk_forward_input.signal_name:
        raise ValueError("feature replay input signal name mismatch")
    if feature_input.dataset_version != walk_forward_input.dataset_version:
        raise ValueError("feature replay input dataset version mismatch")
    if feature_input.feature_version != walk_forward_input.feature_version:
        raise ValueError("feature replay input feature version mismatch")
    regenerated_events = replay_risk_churn_feature_input(feature_input)
    _require_event_match(regenerated_events, walk_forward_input.events)


def _validate_walk_forward_input_binding(
    source: WalkForwardStudyReport,
    replay_input: WalkForwardReplayInput,
) -> None:
    if replay_input.signal_name != source.signal_name:
        raise ValueError("walk-forward replay input signal name mismatch")
    if replay_input.dataset_version != source.dataset_version:
        raise ValueError("walk-forward replay input dataset version mismatch")
    if replay_input.feature_version != source.feature_version:
        raise ValueError("walk-forward replay input feature version mismatch")
    if replay_input.code_sha != source.code_sha:
        raise ValueError("walk-forward replay input code SHA mismatch")
    if replay_input.definition != source.definition:
        raise ValueError("walk-forward replay input signal definition mismatch")
    effective_event_config = replay_input.event_study_config.model_copy(
        update={"walk_forward_splits": []}
    )
    if effective_event_config != source.event_study_config:
        raise ValueError("walk-forward replay input event-study config mismatch")
    if replay_input.walk_forward_config != source.walk_forward_config:
        raise ValueError("walk-forward replay input fold config mismatch")
    if replay_input.market_data_version != source.market_data_version:
        raise ValueError("walk-forward replay input market-data version mismatch")


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


def _normalize_promotion_slices(
    slices: dict[str, set[str]],
) -> dict[str, list[str]]:
    return {
        name: sorted({ticker.upper() for ticker in members})
        for name, members in sorted(slices.items())
    }


def _validate_manifest_version(manifest: ResearchExperimentManifest) -> None:
    supported = {
        _REGISTRY_VERSION_V1,
        _REGISTRY_VERSION_V2,
        _REGISTRY_VERSION_V3,
        _REGISTRY_VERSION,
    }
    if manifest.registry_version not in supported:
        raise ValueError(f"unsupported research registry version {manifest.registry_version!r}")
    if manifest.registry_version == _REGISTRY_VERSION_V1:
        return
    if manifest.promotion_slices is None:
        raise ValueError("computational replay manifest is missing frozen promotion slices")
    normalized = {
        name: sorted({ticker.upper() for ticker in members})
        for name, members in sorted(manifest.promotion_slices.items())
    }
    if normalized != manifest.promotion_slices:
        raise ValueError("promotion slice memberships are not canonical")
    if _stable_digest(normalized) != manifest.slice_snapshot_id:
        raise ValueError("promotion slice snapshot mismatch")
    feature_refs = [item for item in manifest.artifacts if item.kind == "feature_input"]
    walk_refs = [item for item in manifest.artifacts if item.kind == "walk_forward_input"]
    if manifest.registry_version == _REGISTRY_VERSION_V2:
        if feature_refs or walk_refs:
            raise ValueError("registry v2 manifest cannot contain replay input artifacts")
    elif manifest.registry_version == _REGISTRY_VERSION_V3:
        if feature_refs or len(walk_refs) != 1:
            raise ValueError("registry v3 manifest requires only one walk-forward replay input")
    else:
        if len(feature_refs) != 1 or len(walk_refs) != 1:
            raise ValueError("registry v4 manifest requires feature and walk-forward replay inputs")


def _required_artifact_kinds(manifest: ResearchExperimentManifest) -> list[ArtifactKind]:
    required = list(_BASE_ARTIFACTS)
    if manifest.registry_version == _REGISTRY_VERSION_V3:
        required.insert(0, "walk_forward_input")
    elif manifest.registry_version == _REGISTRY_VERSION:
        required[0:0] = ["feature_input", "walk_forward_input"]
    return required


def _replay_artifact_chain(
    manifest: ResearchExperimentManifest,
    payloads: dict[ArtifactKind, dict[str, Any]],
) -> ResearchReplayResult:
    missing = [kind for kind in _required_artifact_kinds(manifest) if kind not in payloads]
    if missing:
        raise ValueError("research replay is missing artifacts: " + ", ".join(missing))

    persisted_source = WalkForwardStudyReport.model_validate(payloads["walk_forward"])
    diagnostics = OOSDiagnosticsReport.model_validate(payloads["oos_diagnostics"])
    selection = OOSSelectionSuiteReport.model_validate(payloads["oos_selection"])
    implementation = OOSImplementationReport.model_validate(payloads["oos_implementation"])
    promotion = OOSPromotionReport.model_validate(payloads["oos_promotion"])
    replayed_decisions = [item.model_dump(mode="json") for item in promotion.decisions]
    if replayed_decisions != manifest.final_decisions:
        raise ValueError("replayed final decisions differ from registered manifest")

    if manifest.registry_version == _REGISTRY_VERSION_V1:
        return ResearchReplayResult(
            experiment_id=manifest.experiment_id,
            verified=True,
            artifact_count=len(manifest.artifacts),
            replay_mode="artifact_verification",
            recomputed_artifacts=[],
            final_decisions=replayed_decisions,
        )

    source = persisted_source
    replay_mode: ReplayMode = "downstream_computational_replay"
    recomputed_artifacts = list(_RECOMPUTED_DOWNSTREAM)
    if manifest.registry_version in {_REGISTRY_VERSION_V3, _REGISTRY_VERSION}:
        walk_input = WalkForwardReplayInput.model_validate(payloads["walk_forward_input"])
        if manifest.registry_version == _REGISTRY_VERSION:
            feature_input = RiskChurnFeatureReplayInput.model_validate(payloads["feature_input"])
            regenerated_events = replay_risk_churn_feature_input(feature_input)
            _require_event_match(regenerated_events, walk_input.events)
            replay_mode = "feature_computational_replay"
        else:
            replay_mode = "walk_forward_computational_replay"
        recomputed_source = replay_walk_forward_input(walk_input)
        _require_recomputed_match("walk_forward", recomputed_source, persisted_source)
        source = recomputed_source
        recomputed_artifacts = ["walk_forward", *_RECOMPUTED_DOWNSTREAM]

    if manifest.promotion_slices is None:
        raise ValueError("computational replay manifest is missing frozen promotion slices")
    if selection.input_diagnostics_keys != [diagnostics.diagnostics_key]:
        raise ValueError(
            "computational replay requires exactly one registered diagnostics input"
        )
    slices = {
        name: set(members) for name, members in manifest.promotion_slices.items()
    }
    recomputed_diagnostics = build_oos_diagnostics(source, diagnostics.config)
    _require_recomputed_match("oos_diagnostics", recomputed_diagnostics, diagnostics)
    recomputed_selection = evaluate_oos_selection_suite(
        [recomputed_diagnostics],
        selection.config,
    )
    _require_recomputed_match("oos_selection", recomputed_selection, selection)
    recomputed_implementation = evaluate_oos_implementation(
        source,
        recomputed_selection,
        implementation.config,
    )
    _require_recomputed_match(
        "oos_implementation",
        recomputed_implementation,
        implementation,
    )
    recomputed_promotion = evaluate_oos_promotion(
        source,
        recomputed_diagnostics,
        recomputed_selection,
        recomputed_implementation,
        slices=slices,
        config=promotion.config,
    )
    _require_recomputed_match("oos_promotion", recomputed_promotion, promotion)
    final_decisions = [
        item.model_dump(mode="json") for item in recomputed_promotion.decisions
    ]
    if final_decisions != manifest.final_decisions:
        raise ValueError("computationally replayed decisions differ from registered manifest")
    return ResearchReplayResult(
        experiment_id=manifest.experiment_id,
        verified=True,
        artifact_count=len(manifest.artifacts),
        replay_mode=replay_mode,
        recomputed_artifacts=recomputed_artifacts,
        final_decisions=final_decisions,
    )


def _require_event_match(
    regenerated: list[Any],
    persisted: list[Any],
) -> None:
    regenerated_payload = [item.model_dump(mode="json") for item in regenerated]
    persisted_payload = [item.model_dump(mode="json") for item in persisted]
    if regenerated_payload != persisted_payload:
        raise ValueError("computational replay mismatch for scored_events")


def _require_recomputed_match(
    kind: ArtifactKind,
    recomputed: BaseModel,
    persisted: BaseModel,
) -> None:
    if recomputed.model_dump(mode="json") != persisted.model_dump(mode="json"):
        raise ValueError(f"computational replay mismatch for {kind}")


def _manifest_storage_payload(manifest: ResearchExperimentManifest) -> dict[str, Any]:
    exclude = {"promotion_slices"} if manifest.registry_version == _REGISTRY_VERSION_V1 else set()
    return manifest.model_dump(mode="json", exclude=exclude)


def _manifest_identity(manifest: ResearchExperimentManifest) -> str:
    payload = _manifest_storage_payload(manifest)
    payload.pop("experiment_id", None)
    return _stable_digest(payload)


def _bundle_identity(bundle: ResearchExperimentBundle) -> str:
    payload = bundle.model_dump(mode="json", exclude={"bundle_sha256"})
    if bundle.manifest.registry_version == _REGISTRY_VERSION_V1:
        manifest_payload = cast(dict[str, Any], payload["manifest"])
        manifest_payload.pop("promotion_slices", None)
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
