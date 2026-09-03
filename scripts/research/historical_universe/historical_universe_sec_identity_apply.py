"""Guarded apply for HU identity promotions proven by SEC filing-level symbol evidence.

This command never discovers evidence. It consumes a freshly generated read-only projection from
``historical_universe_sec_identity``, independently validates its hashes and evidence references,
checks every target against the live database, persists the exact SEC/state provenance, and only
then promotes the supported identity rows in one transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityEvidence,
    SecurityIdentityPeriod,
)
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_lineage import normalize_symbol
from fdre.research.historical_universe_sec_identity import (
    SEC_IDENTITY_DECISION_SCHEMA_VERSION,
    SecTradingSymbolEvidence,
    sec_symbol_match_key,
)

PROJECTION_SCHEMA_VERSION = "fdre-hu-sec-identity-projection-v1"
APPLY_SCHEMA_VERSION = "fdre-hu-sec-identity-apply-v1"
SOURCE_SUFFIX = "+sec/xbrl-symbol+fja05680/sp500-state"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"projection {field} must be an integer")
    return value


def _as_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"projection {field} must be a non-empty string")
    return value


def _as_optional_str(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, field=field)


def _as_str_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"projection {field} must be a string list")
    result = tuple(value)
    if tuple(sorted(set(result))) != result:
        raise RuntimeError(f"projection {field} must be sorted and unique")
    return result


def _decision_hash(decision: dict[str, object]) -> str:
    payload = {
        "schema_version": SEC_IDENTITY_DECISION_SCHEMA_VERSION,
        "row_id": _as_int(decision.get("row_id"), field="decision.row_id"),
        "security_id": _as_int(decision.get("security_id"), field="decision.security_id"),
        "cik": _as_str(decision.get("cik"), field="decision.cik"),
        "symbol": _as_str(decision.get("symbol"), field="decision.symbol"),
        "effective_from": _as_str(
            decision.get("effective_from"), field="decision.effective_from"
        ),
        "effective_to": _as_optional_str(
            decision.get("effective_to"), field="decision.effective_to"
        ),
        "prior_source_hash": _as_str(
            decision.get("prior_source_hash"), field="decision.prior_source_hash"
        ),
        "status": _as_str(decision.get("status"), field="decision.status"),
        "state_decision_hash": _as_optional_str(
            decision.get("state_decision_hash"), field="decision.state_decision_hash"
        ),
        "state_lineage_id": _as_optional_str(
            decision.get("state_lineage_id"), field="decision.state_lineage_id"
        ),
        "sec_evidence_ids": _as_str_tuple(
            decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
        ),
        "conflicting_accessions": _as_str_tuple(
            decision.get("conflicting_accessions"), field="decision.conflicting_accessions"
        ),
        "inspected_accessions": _as_str_tuple(
            decision.get("inspected_accessions"), field="decision.inspected_accessions"
        ),
    }
    return _digest(payload)


def _projection_plan_id(decisions: tuple[dict[str, object], ...]) -> str:
    return _digest(
        {
            "schema_version": SEC_IDENTITY_DECISION_SCHEMA_VERSION,
            "decision_hashes": [
                _as_str(item.get("decision_hash"), field="decision.decision_hash")
                for item in decisions
            ],
        }
    )


def _evidence_from_dict(payload: dict[str, object]) -> SecTradingSymbolEvidence:
    try:
        evidence = SecTradingSymbolEvidence(
            row_id=_as_int(payload.get("row_id"), field="evidence.row_id"),
            cik=_as_str(payload.get("cik"), field="evidence.cik"),
            accession_number=_as_str(
                payload.get("accession_number"), field="evidence.accession_number"
            ),
            filing_date=date.fromisoformat(
                _as_str(payload.get("filing_date"), field="evidence.filing_date")
            ),
            form_type=_as_str(payload.get("form_type"), field="evidence.form_type"),
            symbol=_as_str(payload.get("symbol"), field="evidence.symbol"),
            source_url=_as_str(payload.get("source_url"), field="evidence.source_url"),
            payload_sha256=_as_str(
                payload.get("payload_sha256"), field="evidence.payload_sha256"
            ),
            concept_name=_as_str(payload.get("concept_name"), field="evidence.concept_name"),
            context_ref=_as_optional_str(
                payload.get("context_ref"), field="evidence.context_ref"
            ),
        )
    except ValueError as exc:
        raise RuntimeError(f"invalid SEC identity evidence: {exc}") from exc
    claimed = _as_str(payload.get("evidence_id"), field="evidence.evidence_id")
    if evidence.evidence_id != claimed:
        raise RuntimeError(
            f"SEC identity evidence hash mismatch: expected {claimed}, computed {evidence.evidence_id}"
        )
    return evidence


def _validate_projection(
    payload: dict[str, object],
    *,
    expected_plan_id: str,
    expected_promotion_count: int,
) -> tuple[tuple[dict[str, object], ...], dict[str, SecTradingSymbolEvidence]]:
    if payload.get("schema_version") != PROJECTION_SCHEMA_VERSION:
        raise RuntimeError("unsupported SEC identity projection schema")
    if payload.get("mode") != "projection" or payload.get("applied") is not False:
        raise RuntimeError("SEC identity apply requires an unapplied projection artifact")

    claimed_plan_id = _as_str(payload.get("plan_id"), field="plan_id")
    if claimed_plan_id != expected_plan_id:
        raise RuntimeError(
            f"SEC identity projection changed: expected {expected_plan_id}, got {claimed_plan_id}"
        )
    if _as_int(payload.get("filing_error_count"), field="filing_error_count") != 0:
        raise RuntimeError("SEC identity projection contains filing fetch/extraction errors")

    raw_evidence = payload.get("evidence")
    if not isinstance(raw_evidence, list):
        raise RuntimeError("projection evidence must be a list")
    evidence_by_id: dict[str, SecTradingSymbolEvidence] = {}
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise RuntimeError("projection evidence entries must be objects")
        evidence = _evidence_from_dict(item)
        if evidence.evidence_id in evidence_by_id:
            raise RuntimeError(f"duplicate SEC evidence id {evidence.evidence_id}")
        evidence_by_id[evidence.evidence_id] = evidence
    if _as_int(payload.get("sec_evidence_count"), field="sec_evidence_count") != len(
        evidence_by_id
    ):
        raise RuntimeError("projection SEC evidence count does not match evidence payload")

    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RuntimeError("projection decisions must be a list")
    decisions: list[dict[str, object]] = []
    seen_rows: set[int] = set()
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            raise RuntimeError("projection decision entries must be objects")
        decision = dict(raw)
        row_id = _as_int(decision.get("row_id"), field="decision.row_id")
        if row_id in seen_rows:
            raise RuntimeError(f"duplicate SEC identity decision row {row_id}")
        seen_rows.add(row_id)
        claimed_hash = _as_str(decision.get("decision_hash"), field="decision.decision_hash")
        computed_hash = _decision_hash(decision)
        if claimed_hash != computed_hash:
            raise RuntimeError(
                f"SEC identity decision hash mismatch for row {row_id}: "
                f"expected {claimed_hash}, computed {computed_hash}"
            )
        decisions.append(decision)

    decision_tuple = tuple(decisions)
    computed_plan_id = _projection_plan_id(decision_tuple)
    if computed_plan_id != claimed_plan_id:
        raise RuntimeError(
            f"SEC identity plan hash mismatch: expected {claimed_plan_id}, computed {computed_plan_id}"
        )

    status_counts = Counter(_as_str(item.get("status"), field="decision.status") for item in decisions)
    raw_status_counts = payload.get("status_counts")
    if not isinstance(raw_status_counts, dict):
        raise RuntimeError("projection status_counts must be an object")
    summary_counts = {str(key): int(value) for key, value in raw_status_counts.items()}
    if dict(sorted(status_counts.items())) != dict(sorted(summary_counts.items())):
        raise RuntimeError("projection status summary does not match decision payload")
    if status_counts.get("sec_symbol_conflict", 0) != 0:
        raise RuntimeError("SEC identity projection contains symbol conflicts")

    candidates = tuple(
        item
        for item in decisions
        if _as_str(item.get("status"), field="decision.status") == "fully_supported"
    )
    if len(candidates) != expected_promotion_count:
        raise RuntimeError(
            "SEC identity promotion count changed: "
            f"expected {expected_promotion_count}, computed {len(candidates)}"
        )
    if _as_int(payload.get("promotion_candidate_count"), field="promotion_candidate_count") != len(
        candidates
    ):
        raise RuntimeError("projection promotion count does not match decision payload")

    for decision in candidates:
        row_id = _as_int(decision.get("row_id"), field="decision.row_id")
        if decision.get("promotion_candidate") is not True:
            raise RuntimeError(f"fully supported row {row_id} is not marked promotable")
        cik = _as_str(decision.get("cik"), field="decision.cik")
        target = _as_str(decision.get("symbol"), field="decision.symbol")
        target_key = sec_symbol_match_key(target)
        effective_from = date.fromisoformat(
            _as_str(decision.get("effective_from"), field="decision.effective_from")
        )
        raw_effective_to = _as_optional_str(
            decision.get("effective_to"), field="decision.effective_to"
        )
        effective_to = date.fromisoformat(raw_effective_to) if raw_effective_to else None
        state_decision_hash = _as_str(
            decision.get("state_decision_hash"), field="decision.state_decision_hash"
        )
        state_lineage_id = _as_str(
            decision.get("state_lineage_id"), field="decision.state_lineage_id"
        )
        if len(state_decision_hash) != 64 or len(state_lineage_id) != 64:
            raise RuntimeError(f"row {row_id} has invalid state provenance hashes")
        if _as_str_tuple(
            decision.get("conflicting_accessions"), field="decision.conflicting_accessions"
        ):
            raise RuntimeError(f"fully supported row {row_id} contains a conflict")
        evidence_ids = _as_str_tuple(
            decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
        )
        if not evidence_ids:
            raise RuntimeError(f"fully supported row {row_id} has no SEC evidence")
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise RuntimeError(f"row {row_id} references missing SEC evidence {evidence_id}")
            if evidence.row_id != row_id or evidence.cik != cik:
                raise RuntimeError(f"row {row_id} SEC evidence is bound to a different identity/CIK")
            if sec_symbol_match_key(evidence.symbol) != target_key:
                raise RuntimeError(f"row {row_id} SEC evidence symbol does not match the target")
            if evidence.filing_date < effective_from or (
                effective_to is not None and evidence.filing_date >= effective_to
            ):
                raise RuntimeError(f"row {row_id} SEC evidence falls outside the identity interval")

    return candidates, evidence_by_id


def corroborated_identity_source(source: str) -> str:
    if source.endswith(SOURCE_SUFFIX):
        return source
    combined = f"{source}{SOURCE_SUFFIX}"
    if len(combined) > 128:
        raise RuntimeError("corroborated identity source exceeds database limit")
    return combined


def corroborated_identity_source_hash(decision: dict[str, object], *, plan_id: str) -> str:
    return _digest(
        {
            "schema_version": APPLY_SCHEMA_VERSION,
            "row_id": _as_int(decision.get("row_id"), field="decision.row_id"),
            "prior_source_hash": _as_str(
                decision.get("prior_source_hash"), field="decision.prior_source_hash"
            ),
            "projection_plan_id": plan_id,
            "decision_hash": _as_str(
                decision.get("decision_hash"), field="decision.decision_hash"
            ),
            "state_decision_hash": _as_str(
                decision.get("state_decision_hash"), field="decision.state_decision_hash"
            ),
            "state_lineage_id": _as_str(
                decision.get("state_lineage_id"), field="decision.state_lineage_id"
            ),
            "sec_evidence_ids": list(
                _as_str_tuple(
                    decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
                )
            ),
        }
    )


def _assert_live_row(
    session: Session,
    decision: dict[str, object],
) -> SecurityIdentityPeriod:
    row_id = _as_int(decision.get("row_id"), field="decision.row_id")
    row = session.get(SecurityIdentityPeriod, row_id)
    if row is None:
        raise RuntimeError(f"identity row {row_id} no longer exists")
    security_id = _as_int(decision.get("security_id"), field="decision.security_id")
    if row.security_id != security_id:
        raise RuntimeError(f"identity row {row_id} security changed")
    if normalize_symbol(row.symbol) != normalize_symbol(
        _as_str(decision.get("symbol"), field="decision.symbol")
    ):
        raise RuntimeError(f"identity row {row_id} symbol changed")
    if row.effective_from.isoformat() != _as_str(
        decision.get("effective_from"), field="decision.effective_from"
    ):
        raise RuntimeError(f"identity row {row_id} start date changed")
    expected_to = _as_optional_str(decision.get("effective_to"), field="decision.effective_to")
    if (row.effective_to.isoformat() if row.effective_to else None) != expected_to:
        raise RuntimeError(f"identity row {row_id} end date changed")
    if row.source_hash != _as_str(
        decision.get("prior_source_hash"), field="decision.prior_source_hash"
    ):
        raise RuntimeError(f"identity row {row_id} source hash changed")
    if row.verification_status != "provisional":
        raise RuntimeError(f"identity row {row_id} is no longer provisional")

    security = session.get(Security, security_id)
    if security is None:
        raise RuntimeError(f"security {security_id} no longer exists")
    company = session.get(Company, security.company_id)
    if company is None:
        raise RuntimeError(f"company {security.company_id} no longer exists")
    if normalize_cik(company.cik) != _as_str(decision.get("cik"), field="decision.cik"):
        raise RuntimeError(f"identity row {row_id} issuer CIK changed")
    return row


def _stage_candidates(
    session: Session,
    candidates: tuple[dict[str, object], ...],
    evidence_by_id: dict[str, SecTradingSymbolEvidence],
    *,
    plan_id: str,
) -> tuple[int, int, list[dict[str, object]]]:
    all_evidence_ids = tuple(
        sorted(
            {
                evidence_id
                for decision in candidates
                for evidence_id in _as_str_tuple(
                    decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
                )
            }
        )
    )
    if all_evidence_ids:
        existing = tuple(
            session.scalars(
                select(SecurityIdentityEvidence.evidence_id).where(
                    SecurityIdentityEvidence.evidence_id.in_(all_evidence_ids)
                )
            )
        )
        if existing:
            raise RuntimeError(
                "SEC identity evidence already exists for this apply: " + ", ".join(sorted(existing))
            )

    applied_rows: list[dict[str, object]] = []
    evidence_count = 0
    for decision in sorted(candidates, key=lambda item: _as_int(item.get("row_id"), field="row_id")):
        row = _assert_live_row(session, decision)
        row_id = row.id
        decision_hash = _as_str(decision.get("decision_hash"), field="decision.decision_hash")
        state_decision_hash = _as_str(
            decision.get("state_decision_hash"), field="decision.state_decision_hash"
        )
        state_lineage_id = _as_str(
            decision.get("state_lineage_id"), field="decision.state_lineage_id"
        )
        evidence_ids = _as_str_tuple(
            decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
        )
        for evidence_id in evidence_ids:
            evidence = evidence_by_id[evidence_id]
            session.add(
                SecurityIdentityEvidence(
                    evidence_id=evidence.evidence_id,
                    security_identity_period_id=row_id,
                    cik=evidence.cik,
                    symbol=evidence.symbol,
                    accession_number=evidence.accession_number,
                    filing_date=evidence.filing_date,
                    form_type=evidence.form_type,
                    concept_name=evidence.concept_name,
                    context_ref=evidence.context_ref,
                    source_url=evidence.source_url,
                    payload_sha256=evidence.payload_sha256,
                    decision_hash=decision_hash,
                    state_decision_hash=state_decision_hash,
                    state_lineage_id=state_lineage_id,
                    projection_plan_id=plan_id,
                )
            )
            evidence_count += 1

        prior_source = row.source
        prior_source_hash = row.source_hash
        row.source = corroborated_identity_source(row.source)
        row.source_hash = corroborated_identity_source_hash(decision, plan_id=plan_id)
        row.verification_status = "verified"
        row.confidence = max(float(row.confidence), 0.98)
        applied_rows.append(
            {
                "row_id": row_id,
                "security_id": row.security_id,
                "symbol": row.symbol,
                "prior_source": prior_source,
                "source": row.source,
                "prior_source_hash": prior_source_hash,
                "source_hash": row.source_hash,
                "decision_hash": decision_hash,
                "sec_evidence_ids": list(evidence_ids),
            }
        )

    session.flush()
    return len(applied_rows), evidence_count, applied_rows


def _validate_apply_request(*, apply: bool, expected_plan_id: str, allow_prod: bool) -> None:
    if not apply:
        raise RuntimeError("SEC identity apply requires explicit --apply")
    if not allow_prod:
        raise RuntimeError("--apply requires FDRE_ALLOW_PROD=1")
    if len(expected_plan_id) != 64:
        raise RuntimeError("--expected-plan-id must be a SHA-256 plan id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a validated SEC filing-level HU identity projection."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--expected-plan-id", required=True)
    parser.add_argument("--expected-promotion-count", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _validate_apply_request(
        apply=args.apply,
        expected_plan_id=args.expected_plan_id,
        allow_prod=os.environ.get("FDRE_ALLOW_PROD") == "1",
    )
    if args.expected_promotion_count < 1:
        raise RuntimeError("--expected-promotion-count must be positive")

    raw_payload: Any = json.loads(args.projection.read_text(encoding="utf-8"))
    if not isinstance(raw_payload, dict):
        raise RuntimeError("SEC identity projection root must be an object")
    payload: dict[str, object] = raw_payload
    candidates, evidence_by_id = _validate_projection(
        payload,
        expected_plan_id=args.expected_plan_id,
        expected_promotion_count=args.expected_promotion_count,
    )

    engine = create_db_engine(args.database_url)
    applied_rows: list[dict[str, object]]
    try:
        with Session(engine) as session:
            applied_count, evidence_count, applied_rows = _stage_candidates(
                session,
                candidates,
                evidence_by_id,
                plan_id=args.expected_plan_id,
            )
            if applied_count != args.expected_promotion_count:
                raise RuntimeError(
                    f"staged {applied_count} identity rows; expected {args.expected_promotion_count}"
                )
            expected_evidence_count = sum(
                len(
                    _as_str_tuple(
                        decision.get("sec_evidence_ids"), field="decision.sec_evidence_ids"
                    )
                )
                for decision in candidates
            )
            if evidence_count != expected_evidence_count:
                raise RuntimeError(
                    f"staged {evidence_count} SEC evidence rows; expected {expected_evidence_count}"
                )
            session.commit()
    finally:
        engine.dispose()

    result = {
        "schema_version": APPLY_SCHEMA_VERSION,
        "mode": "apply",
        "applied": True,
        "plan_id": args.expected_plan_id,
        "applied_identity_updates": len(applied_rows),
        "persisted_sec_evidence_count": sum(
            len(item["sec_evidence_ids"]) for item in applied_rows
        ),
        "rows": applied_rows,
        "interpretation": (
            "Applied only identity rows whose freshly replayed projection exactly matched the "
            "expected plan, live provisional row state, issuer CIK, full ticker-state containment, "
            "and immutable SEC TradingSymbol evidence. Exact SEC payload/state provenance was "
            "persisted before the transaction committed."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": args.expected_plan_id,
                "applied_identity_updates": result["applied_identity_updates"],
                "persisted_sec_evidence_count": result["persisted_sec_evidence_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
