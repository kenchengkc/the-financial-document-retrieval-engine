"""Immutable inputs for offline walk-forward computational replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiments.event_study import EventStudyConfig, FilingEvent, MarketBar
from fdre.research.experiments.walk_forward import (
    WalkForwardConfig,
    WalkForwardStudyReport,
    market_data_version,
    run_walk_forward_signal_study,
)

_REPLAY_INPUT_VERSION = "walk-forward-replay-input-v1"


class WalkForwardReplayInput(BaseModel):
    """Frozen scored events and market bars required to reconstruct a walk-forward study."""

    input_key: str
    replay_input_version: str = _REPLAY_INPUT_VERSION
    signal_name: str
    dataset_version: str
    feature_version: str
    code_sha: str
    definition: dict[str, object]
    event_study_config: EventStudyConfig
    walk_forward_config: WalkForwardConfig
    market_data_version: str
    events: list[FilingEvent]
    bars: list[MarketBar]


def build_walk_forward_replay_input(
    events: list[FilingEvent],
    bars: list[MarketBar],
    event_study_config: EventStudyConfig,
    walk_forward_config: WalkForwardConfig,
    *,
    signal_name: str,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    definition: dict[str, object] | None = None,
) -> WalkForwardReplayInput:
    """Freeze the exact in-memory inputs consumed by a walk-forward study."""

    payload = {
        "replay_input_version": _REPLAY_INPUT_VERSION,
        "signal_name": signal_name,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "code_sha": code_sha,
        "definition": definition or {},
        "event_study_config": event_study_config.model_dump(mode="json"),
        "walk_forward_config": walk_forward_config.model_dump(mode="json"),
        "market_data_version": market_data_version(bars),
        "events": [item.model_dump(mode="json") for item in events],
        "bars": [item.model_dump(mode="json") for item in bars],
    }
    return WalkForwardReplayInput(input_key=_stable_digest(payload), **payload)


def replay_walk_forward_input(replay_input: WalkForwardReplayInput) -> WalkForwardStudyReport:
    """Recompute a sealed walk-forward study using only the frozen replay artifact."""

    if _replay_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("walk-forward replay input digest mismatch")
    actual_market_version = market_data_version(replay_input.bars)
    if actual_market_version != replay_input.market_data_version:
        raise ValueError("walk-forward replay market-data digest mismatch")
    return run_walk_forward_signal_study(
        replay_input.events,
        replay_input.bars,
        replay_input.event_study_config,
        replay_input.walk_forward_config,
        signal_name=replay_input.signal_name,
        dataset_version=replay_input.dataset_version,
        feature_version=replay_input.feature_version,
        code_sha=replay_input.code_sha,
        definition=replay_input.definition,
    )


def persist_walk_forward_replay_input(
    session: Session,
    replay_input: WalkForwardReplayInput,
) -> ResearchExperiment:
    """Persist the replay input immutably in the generic research artifact store."""

    if _replay_input_identity(replay_input) != replay_input.input_key:
        raise ValueError("walk-forward replay input digest mismatch")
    payload = replay_input.model_dump(mode="json")
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == replay_input.input_key
        )
    )
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=replay_input.input_key,
            experiment_type="walk_forward_replay_input",
            dataset_version=replay_input.dataset_version,
            feature_version=replay_input.feature_version,
            code_sha=replay_input.code_sha,
            config_json={
                "replay_input_version": replay_input.replay_input_version,
                "signal_name": replay_input.signal_name,
                "market_data_version": replay_input.market_data_version,
            },
            results_json=payload,
        )
        session.add(experiment)
    elif experiment.results_json != payload:
        raise ValueError("walk-forward replay input payload mismatch")
    else:
        return experiment
    session.commit()
    session.refresh(experiment)
    return experiment


def write_walk_forward_replay_input(
    path: str | Path,
    replay_input: WalkForwardReplayInput,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(replay_input.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _replay_input_identity(replay_input: WalkForwardReplayInput) -> str:
    payload = replay_input.model_dump(mode="json", exclude={"input_key"})
    return _stable_digest(payload)


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
