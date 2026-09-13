"""Signal-specific immutable inputs for reproducible feature construction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiments.event_study import FilingEvent
from fdre.research.panel import FEATURE_VERSION, ResearchPanelRow
from fdre.research.signals.risk_churn_acceleration import (
    RISK_CHURN_ACCELERATION_VERSION,
    RISK_CHURN_NEUTRALIZATION_VERSION,
    RISK_CHURN_SIGNAL_NAME,
    build_neutralized_risk_churn_acceleration_events,
)

_FEATURE_REPLAY_VERSION = "risk-churn-feature-replay-input-v1"
_FEATURE_VERSION = (
    f"{RISK_CHURN_ACCELERATION_VERSION}+{RISK_CHURN_NEUTRALIZATION_VERSION}"
)


class RiskChurnFeatureReplayInput(BaseModel):
    """PIT panel rows and sector identities needed to regenerate flagship scores."""

    input_key: str
    replay_input_version: str = _FEATURE_REPLAY_VERSION
    signal_name: str = RISK_CHURN_SIGNAL_NAME
    dataset_version: str
    panel_feature_version: str = FEATURE_VERSION
    feature_version: str = _FEATURE_VERSION
    corpus_snapshot_id: str
    neutralization_min_group: int = Field(default=4, ge=2)
    sector_by_ticker: dict[str, str]
    rows: list[ResearchPanelRow]


def build_risk_churn_feature_replay_input(
    rows: list[ResearchPanelRow],
    sector_by_ticker: dict[str, str],
    *,
    neutralization_min_group: int = 4,
) -> RiskChurnFeatureReplayInput:
    """Freeze exact PIT feature inputs before signal construction and neutralization."""

    snapshots = {row.corpus_snapshot_id for row in rows}
    if len(snapshots) != 1:
        raise ValueError("risk-churn feature replay requires one corpus snapshot")
    corpus_snapshot_id = next(iter(snapshots))
    normalized_sectors = {
        ticker.upper(): sector
        for ticker, sector in sorted(sector_by_ticker.items())
    }
    payload: dict[str, Any] = {
        "replay_input_version": _FEATURE_REPLAY_VERSION,
        "signal_name": RISK_CHURN_SIGNAL_NAME,
        "dataset_version": f"panel:{corpus_snapshot_id}",
        "panel_feature_version": FEATURE_VERSION,
        "feature_version": _FEATURE_VERSION,
        "corpus_snapshot_id": corpus_snapshot_id,
        "neutralization_min_group": neutralization_min_group,
        "sector_by_ticker": normalized_sectors,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    return RiskChurnFeatureReplayInput(
        input_key=_stable_digest(payload),
        **payload,
    )


def replay_risk_churn_feature_input(
    replay_input: RiskChurnFeatureReplayInput,
) -> list[FilingEvent]:
    """Regenerate scored flagship events without database or provider access."""

    if _feature_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("risk-churn feature replay input digest mismatch")
    if replay_input.signal_name != RISK_CHURN_SIGNAL_NAME:
        raise ValueError("risk-churn feature replay signal mismatch")
    if replay_input.panel_feature_version != FEATURE_VERSION:
        raise ValueError("risk-churn feature replay panel version mismatch")
    if replay_input.feature_version != _FEATURE_VERSION:
        raise ValueError("risk-churn feature replay calculation version mismatch")
    if replay_input.dataset_version != f"panel:{replay_input.corpus_snapshot_id}":
        raise ValueError("risk-churn feature replay dataset version mismatch")
    if any(
        row.corpus_snapshot_id != replay_input.corpus_snapshot_id
        for row in replay_input.rows
    ):
        raise ValueError("risk-churn feature replay row snapshot mismatch")
    return build_neutralized_risk_churn_acceleration_events(
        replay_input.rows,
        replay_input.sector_by_ticker,
        min_group=replay_input.neutralization_min_group,
    )


def persist_risk_churn_feature_replay_input(
    session: Session,
    replay_input: RiskChurnFeatureReplayInput,
) -> ResearchExperiment:
    """Persist a content-addressed feature replay input immutably."""

    if _feature_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("risk-churn feature replay input digest mismatch")
    payload = replay_input.model_dump(mode="json")
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == replay_input.input_key
        )
    )
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=replay_input.input_key,
            experiment_type="risk_churn_feature_replay_input",
            dataset_version=replay_input.dataset_version,
            feature_version=replay_input.feature_version,
            code_sha="deterministic-feature-replay",
            config_json={
                "replay_input_version": replay_input.replay_input_version,
                "signal_name": replay_input.signal_name,
                "corpus_snapshot_id": replay_input.corpus_snapshot_id,
                "panel_feature_version": replay_input.panel_feature_version,
            },
            results_json=payload,
        )
        session.add(experiment)
    elif experiment.results_json != payload:
        raise ValueError("risk-churn feature replay input payload mismatch")
    else:
        return experiment
    session.commit()
    session.refresh(experiment)
    return experiment


def write_risk_churn_feature_replay_input(
    path: str | Path,
    replay_input: RiskChurnFeatureReplayInput,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(replay_input.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _feature_input_identity(replay_input: RiskChurnFeatureReplayInput) -> str:
    return _stable_digest(
        replay_input.model_dump(mode="json", exclude={"input_key"})
    )


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
