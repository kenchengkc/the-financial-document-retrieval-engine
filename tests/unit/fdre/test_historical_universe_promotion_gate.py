from __future__ import annotations

from pathlib import Path

from scripts.research.historical_universe.historical_universe_promotion_gate import evaluate


def _component_history(path: Path) -> Path:
    path.write_text(
        "symbol,cik,name,sector,date_added,date_removed,created_at\n",
        encoding="utf-8",
    )
    return path


def _coverage() -> dict[str, object]:
    return {
        "audit_id": "audit-1",
        "deterministic_replay_match": True,
        "current_constituent_reconciliation": {
            "missing_catalog_symbols": [],
            "missing_active_security_identity_symbols": [],
            "ambiguous_active_security_identity_symbols": [],
        },
    }


def _remediation() -> dict[str, object]:
    return {
        "target_window": {"security_resolution_rate": 0.96},
        "raw_evidence_diagnostics": {"same_date_symbol_opposing_event_keys": []},
    }


def _anchor() -> dict[str, object]:
    return {
        "anchor_id": "anchor-1",
        "universe_code": "sp500",
        "effective_at": "2009-12-30",
        "constituent_count": 500,
        "complete_target_window_anchor": True,
    }


def _materialization() -> dict[str, object]:
    return {
        "applied": True,
        "validation": {
            "anchor_id": "anchor-1",
            "universe_code": "sp500",
            "as_of": "2009-12-30",
            "expected_constituent_count": 500,
            "commit_eligible": True,
            "provisional_anchor_match": True,
            "strict_anchor_match": True,
            "deterministic_replay_match": True,
            "identity_overlap_count": 0,
            "membership_overlap_count": 0,
            "missing_identity_coverage_count": 0,
        },
    }


def _anchor_reconciliation() -> dict[str, object]:
    return {
        "anchor_reconciled": True,
        "production_identity_ready": True,
        "identity_safe_anchor": {
            "anchor_id": "anchor-1",
            "universe_code": "sp500",
            "effective_at": "2009-12-30",
            "constituent_count": 500,
        },
    }


def _boundary_audit() -> dict[str, object]:
    return {
        "interval_count": 1,
        "intervals": [{"record_id": "record-1", "status": "verified"}],
        "status_counts": {"verified": 1},
        "production_apply_eligible": True,
    }


def _requirements(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_requirements = payload["requirements"]
    assert isinstance(raw_requirements, list)
    result: dict[str, dict[str, object]] = {}
    for row in raw_requirements:
        assert isinstance(row, dict)
        result[str(row["id"])] = row
    return result


def test_gate_requires_committed_validated_materialization(tmp_path: Path) -> None:
    payload = evaluate(
        coverage=_coverage(),
        remediation=_remediation(),
        anchor=_anchor(),
        anchor_reconciliation=_anchor_reconciliation(),
        boundary_audit=_boundary_audit(),
        materialization=_materialization(),
        component_history=_component_history(tmp_path / "components.csv"),
        component_history_ref="a" * 40,
    )

    assert payload["promotion_gate_met"] is True


def test_gate_fails_for_nonmutating_plan_without_staged_validation(tmp_path: Path) -> None:
    materialization = {
        "applied": False,
        "validation": {
            "anchor_id": "anchor-1",
            "universe_code": "sp500",
            "as_of": "2009-12-30",
            "status": "not_run",
            "commit_eligible": False,
        },
    }
    payload = evaluate(
        coverage=_coverage(),
        remediation=_remediation(),
        anchor=_anchor(),
        anchor_reconciliation=_anchor_reconciliation(),
        boundary_audit=_boundary_audit(),
        materialization=materialization,
        component_history=_component_history(tmp_path / "components.csv"),
        component_history_ref="a" * 40,
    )

    requirements = _requirements(payload)
    assert payload["promotion_gate_met"] is False
    assert requirements["materialization_committed_after_validation"]["met"] is False
    assert requirements["materialized_strict_snapshot_matches_anchor"]["met"] is False


def test_gate_rejects_materialization_validated_against_another_anchor(
    tmp_path: Path,
) -> None:
    materialization = _materialization()
    validation = materialization["validation"]
    assert isinstance(validation, dict)
    validation["anchor_id"] = "other-anchor"

    payload = evaluate(
        coverage=_coverage(),
        remediation=_remediation(),
        anchor=_anchor(),
        anchor_reconciliation=_anchor_reconciliation(),
        boundary_audit=_boundary_audit(),
        materialization=materialization,
        component_history=_component_history(tmp_path / "components.csv"),
        component_history_ref="a" * 40,
    )

    requirements = _requirements(payload)
    assert payload["promotion_gate_met"] is False
    assert requirements["materialized_anchor_alignment"]["met"] is False


def test_gate_retains_reconciled_but_unresolved_anchor_and_boundaries(
    tmp_path: Path,
) -> None:
    anchor_reconciliation = _anchor_reconciliation()
    anchor_reconciliation["production_identity_ready"] = False
    boundary_audit = _boundary_audit()
    boundary_audit["production_apply_eligible"] = False

    payload = evaluate(
        coverage=_coverage(),
        remediation=_remediation(),
        anchor=_anchor(),
        anchor_reconciliation=anchor_reconciliation,
        boundary_audit=boundary_audit,
        materialization=_materialization(),
        component_history=_component_history(tmp_path / "components.csv"),
        component_history_ref="a" * 40,
    )

    requirements = _requirements(payload)
    assert payload["promotion_gate_met"] is False
    assert requirements["anchor_symbol_discrepancies_reconciled"]["met"] is True
    assert requirements["anchor_identity_remediation_complete"]["met"] is False
    assert requirements["provisional_boundaries_explicitly_adjudicated"]["met"] is True
    assert requirements["post_anchor_boundaries_production_ready"]["met"] is False
