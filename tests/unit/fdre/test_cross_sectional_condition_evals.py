from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from fdre.evals.cross_sectional import (
    CrossSectionalOutcome,
    evaluate_cross_sectional_outcomes,
)
from fdre.evals.cross_sectional_reporting import write_cross_sectional_eval_report
from fdre.evals.datasets import EvalQuestion
from fdre.research.screen import (
    ResearchScreenManifest,
    ResearchScreenPlan,
    ResearchScreenResponse,
    ResearchScreenRow,
    ScreenCondition,
    ScreenConditionResult,
)

AS_OF = datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC)
ACCESSION = "0001193125-26-191507"
PRIOR_ACCESSION = "0000950170-25-061046"
LINEAGE_ID = "8b0456f564301cc38537dd882671fbac779d927f47b2618a2d95833e9ebe0868"


def _question(*, lineage_id: str = LINEAGE_ID) -> EvalQuestion:
    return EvalQuestion(
        question_id="structured-condition-001",
        question="Which issuer has operating margin above 40%?",
        category="cross_sectional",
        task_type="structured_screen",
        expected_tickers=["MSFT"],
        as_of=AS_OF.isoformat(),
        metadata={
            "reviewed_by": "test",
            "selected_accession": ACCESSION,
            "selected_prior_accession": PRIOR_ACCESSION,
            "screen_plan": {
                "tickers": ["MSFT", "ABBV"],
                "form_types": ["10-Q"],
                "conditions": [
                    {
                        "metric": "operating_margin",
                        "operator": "gt",
                        "value": 0.4,
                    }
                ],
                "rank_by": "operating_margin",
            },
            "expected_conditions": [
                {
                    "metric": "operating_margin",
                    "feature": "xbrl_margins",
                    "operator": "gt",
                    "threshold": 0.4,
                    "change_from_prior": False,
                    "passed": True,
                    "current_value": 0.4589030752668268,
                    "prior_value": None,
                    "observed_value": 0.4589030752668268,
                    "current_lineage_id": lineage_id,
                    "prior_lineage_id": None,
                    "source_accessions": [ACCESSION],
                }
            ],
        },
    )


def _response() -> ResearchScreenResponse:
    condition = ScreenCondition(
        metric="operating_margin",
        operator="gt",
        value=0.4,
    )
    plan = ResearchScreenPlan(
        tickers=["MSFT", "ABBV"],
        as_of=AS_OF,
        form_types=["10-Q"],
        conditions=[condition],
        rank_by="operating_margin",
    )
    row = ResearchScreenRow(
        ticker="MSFT",
        accession_number=ACCESSION,
        prior_accession_number=PRIOR_ACCESSION,
        form_type="10-Q",
        period_end=date(2026, 3, 31),
        available_at=datetime(2026, 4, 29, 20, 6, 24, tzinfo=UTC),
        semantic_score=None,
        rank_value=0.4589030752668268,
        conditions=[
            ScreenConditionResult(
                metric="operating_margin",
                feature="xbrl_margins",
                operator="gt",
                threshold=0.4,
                change_from_prior=False,
                current_value=0.4589030752668268,
                prior_value=None,
                observed_value=0.4589030752668268,
                passed=True,
                current_lineage_id=LINEAGE_ID,
                prior_lineage_id=None,
                source_accessions=[ACCESSION],
                max_information_timestamp=datetime(
                    2026,
                    4,
                    29,
                    20,
                    6,
                    24,
                    tzinfo=UTC,
                ),
            )
        ],
        evidence=[],
        source_accessions=[ACCESSION, PRIOR_ACCESSION],
        feature_provenance={"xbrl_features": [ACCESSION, PRIOR_ACCESSION]},
        max_source_available_at=datetime(2026, 4, 29, 20, 6, 24, tzinfo=UTC),
    )
    return ResearchScreenResponse(
        plan=plan,
        manifest=ResearchScreenManifest(
            plan_hash="plan",
            feature_lineage_digest="0" * 64,
            corpus_snapshot_id="snapshot",
            feature_version="fdre-panel-v3",
            universe_count=2,
            structured_match_count=1,
            semantic_search_calls=0,
            semantic_candidate_count=0,
            matched_count=1,
            max_information_timestamp=row.max_source_available_at,
        ),
        rows=[row],
        latency_ms=25,
    )


def test_condition_grounding_scores_exact_numeric_and_lineage_reason() -> None:
    semantic_question = EvalQuestion(
        question_id="semantic-no-condition",
        question="Semantic control",
        category="cross_sectional",
        task_type="semantic_screen",
        expected_tickers=["MSFT"],
        metadata={"reviewed_by": "test"},
    )
    response = _response()

    metrics = evaluate_cross_sectional_outcomes(
        [
            CrossSectionalOutcome(question=_question(), response=response),
            CrossSectionalOutcome(question=semantic_question, response=response),
        ],
        ks=(1,),
    )

    assert metrics.condition_grounding_question_count == 1
    assert metrics.condition_correctness_accuracy == 1.0
    assert metrics.condition_lineage_replay_accuracy == 1.0
    assert metrics.condition_grounding_accuracy == 1.0
    assert metrics.per_question[0].reviewed_condition_count == 1
    assert metrics.per_question[0].condition_correct is True
    assert metrics.per_question[0].condition_lineage_replay_correct is True
    assert metrics.per_question[0].condition_grounding_correct is True
    assert metrics.per_question[1].reviewed_condition_count == 0
    assert metrics.per_question[1].condition_correct is None
    assert metrics.per_question[1].condition_lineage_replay_correct is None
    assert metrics.per_question[1].condition_grounding_correct is None


def test_condition_grounding_separates_snapshot_lineage_mismatch() -> None:
    metrics = evaluate_cross_sectional_outcomes(
        [
            CrossSectionalOutcome(
                question=_question(lineage_id="f" * 64),
                response=_response(),
            )
        ],
        ks=(1,),
    )

    assert metrics.condition_grounding_question_count == 1
    assert metrics.condition_correctness_accuracy == 1.0
    assert metrics.condition_lineage_replay_accuracy == 0.0
    assert metrics.condition_grounding_accuracy == 0.0
    assert metrics.per_question[0].condition_correct is True
    assert metrics.per_question[0].condition_lineage_replay_correct is False
    assert metrics.per_question[0].condition_grounding_correct is False


def test_condition_grounding_is_emitted_in_reproducible_reports(tmp_path: Path) -> None:
    metrics = evaluate_cross_sectional_outcomes(
        [CrossSectionalOutcome(question=_question(), response=_response())],
        ks=(1,),
    )
    json_path, markdown_path, per_query_path = write_cross_sectional_eval_report(
        tmp_path,
        metrics,
        benchmark_metadata={"dataset_sha256": "abc"},
    )

    payload = json.loads(json_path.read_text())
    assert payload["overall"]["condition_grounding_question_count"] == 1
    assert payload["overall"]["condition_correctness_accuracy"] == 1.0
    assert payload["overall"]["condition_lineage_replay_accuracy"] == 1.0
    assert payload["overall"]["condition_grounding_accuracy"] == 1.0
    task_payload = payload["by_task_type"]["structured_screen"]
    assert task_payload["condition_correctness_accuracy"] == 1.0
    assert task_payload["condition_lineage_replay_accuracy"] == 1.0
    assert task_payload["condition_grounding_accuracy"] == 1.0

    record = json.loads(per_query_path.read_text())
    assert record["reviewed_condition_count"] == 1
    assert record["condition_correct"] is True
    assert record["condition_lineage_replay_correct"] is True
    assert record["condition_grounding_correct"] is True

    markdown = markdown_path.read_text()
    assert "Condition correctness/source grounding" in markdown
    assert "Exact lineage replay" in markdown
    assert "Strict condition grounding" in markdown
    assert "100.000%" in markdown
