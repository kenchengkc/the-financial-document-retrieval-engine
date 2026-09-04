"""Collect exact SEC TradingSymbol evidence for frozen residual HU-5 identity blockers.

This command is read-only. Targets come from the frozen residual topology rather than from ticker
state support. It revalidates every target against live database identity fields, inspects bounded
8-K/10-Q/10-K filings filed inside that identity interval, and emits exact issuer→symbol evidence.
It does not promote identities or repair boundaries.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from apps.api.app.models.historical_universe import Security, SecurityIdentityPeriod
from fdre.ingestion.sec_client import SECClient
from fdre.research.historical_universe_residual_sec_evidence import (
    RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
    ResidualSecTarget,
    plan_residual_sec_evidence,
    residual_sec_plan_id,
)
from fdre.research.historical_universe_sec_identity import (
    SecIdentityFilingObservation,
    SecTradingSymbolEvidence,
)
from scripts.research.historical_universe.historical_universe_sec_identity import (
    CandidateDocument,
    FetchedFiling,
    _fetch_filing,
)

FORMS = ("10-K", "10-Q", "8-K")


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _load_topology(
    path: Path,
    *,
    expected_topology_id: str | None,
) -> tuple[str, date, tuple[ResidualSecTarget, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    topology_id = str(payload.get("topology_id", ""))
    if len(topology_id) != 64:
        raise ValueError("topology payload is missing a SHA-256 topology_id")
    if expected_topology_id and topology_id != expected_topology_id:
        raise ValueError(
            f"topology drift: expected {expected_topology_id}, got {topology_id}"
        )
    window_end = _date(str(payload["window_end"]))
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raise ValueError("topology payload targets must be a list")

    targets: list[ResidualSecTarget] = []
    for raw in raw_targets:
        if not isinstance(raw, dict):
            raise ValueError("topology target must be an object")
        targets.append(
            ResidualSecTarget(
                identity_id=int(raw["identity_id"]),
                security_id=int(raw["security_id"]),
                cik=str(raw["cik"]),
                symbol=str(raw["symbol"]),
                effective_from=_date(str(raw["effective_from"])),
                effective_to=(
                    _date(str(raw["effective_to"]))
                    if raw.get("effective_to") is not None
                    else None
                ),
                source_hash=str(raw["source_hash"]),
            )
        )
    ordered = tuple(sorted(targets, key=lambda item: item.identity_id))
    if len({item.identity_id for item in ordered}) != len(ordered):
        raise ValueError("topology contains duplicate residual identity targets")
    return topology_id, window_end, ordered


def _revalidate_targets(
    session: Session,
    targets: tuple[ResidualSecTarget, ...],
) -> dict[int, int]:
    identity_ids = tuple(item.identity_id for item in targets)
    if not identity_ids:
        return {}
    rows = session.execute(
        select(
            SecurityIdentityPeriod.id,
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.verification_status,
            SecurityIdentityPeriod.source_hash,
            Company.id.label("company_id"),
            Company.cik,
        )
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(SecurityIdentityPeriod.id.in_(identity_ids))
        .order_by(SecurityIdentityPeriod.id)
    ).all()
    by_id = {int(row.id): row for row in rows}
    if set(by_id) != set(identity_ids):
        missing = sorted(set(identity_ids) - set(by_id))
        raise RuntimeError(f"residual identity targets disappeared: {missing}")

    company_by_identity: dict[int, int] = {}
    for target in targets:
        row = by_id[target.identity_id]
        live = {
            "security_id": int(row.security_id),
            "cik": str(row.cik),
            "symbol": str(row.symbol),
            "effective_from": row.effective_from,
            "effective_to": row.effective_to,
            "verification_status": str(row.verification_status),
            "source_hash": str(row.source_hash),
        }
        expected = {
            "security_id": target.security_id,
            "cik": target.cik,
            "symbol": target.symbol,
            "effective_from": target.effective_from,
            "effective_to": target.effective_to,
            "verification_status": "provisional",
            "source_hash": target.source_hash,
        }
        if live != expected:
            raise RuntimeError(
                f"residual identity {target.identity_id} drifted: "
                f"expected {expected}, got {live}"
            )
        company_by_identity[target.identity_id] = int(row.company_id)
    return company_by_identity


def _load_documents(
    session: Session,
    company_ids: tuple[int, ...],
    *,
    minimum_date: date,
    maximum_date: date,
) -> dict[int, tuple[CandidateDocument, ...]]:
    if not company_ids:
        return {}
    rows = session.execute(
        select(
            Document.id,
            Document.company_id,
            Document.accession_number,
            Document.filing_date,
            Document.form_type,
            Document.primary_document_url,
        )
        .where(
            Document.company_id.in_(company_ids),
            Document.source_type == "sec",
            Document.form_type.in_(FORMS),
            Document.is_amendment.is_(False),
            Document.filing_date.is_not(None),
            Document.filing_date >= minimum_date,
            Document.filing_date <= maximum_date,
            Document.primary_document_url.is_not(None),
        )
        .order_by(Document.company_id, Document.filing_date, Document.accession_number)
    ).all()
    grouped: dict[int, list[CandidateDocument]] = defaultdict(list)
    for row in rows:
        if row.filing_date is None or row.primary_document_url is None:
            continue
        grouped[int(row.company_id)].append(
            CandidateDocument(
                document_id=int(row.id),
                company_id=int(row.company_id),
                accession_number=str(row.accession_number),
                filing_date=row.filing_date,
                form_type=str(row.form_type).upper(),
                primary_document_url=str(row.primary_document_url),
            )
        )
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _candidate_documents(
    target: ResidualSecTarget,
    documents: tuple[CandidateDocument, ...],
    *,
    window_end: date,
    limit: int,
) -> tuple[CandidateDocument, ...]:
    upper = target.effective_to or (window_end + date.resolution)
    eligible = [
        item
        for item in documents
        if target.effective_from <= item.filing_date < upper
    ]
    if not eligible:
        return ()

    selected: list[CandidateDocument] = []
    seen: set[int] = set()

    def add(item: CandidateDocument | None) -> None:
        if item is None or item.document_id in seen or len(selected) >= limit:
            return
        selected.append(item)
        seen.add(item.document_id)

    # Preserve one observation near the identity boundary, then one recent observation per form.
    add(min(eligible, key=lambda item: (item.filing_date, item.accession_number)))
    for form_type in FORMS:
        form_rows = [item for item in eligible if item.form_type == form_type]
        add(
            max(
                form_rows,
                key=lambda item: (item.filing_date, item.accession_number),
                default=None,
            )
        )
    for item in sorted(
        eligible,
        key=lambda candidate: (candidate.filing_date, candidate.accession_number),
        reverse=True,
    ):
        add(item)
    return tuple(selected)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect SEC issuer-symbol evidence for frozen residual HU-5 identities."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--expected-topology-id")
    parser.add_argument("--max-filings-per-identity", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_filings_per_identity < 1 or args.max_filings_per_identity > 10:
        raise ValueError("--max-filings-per-identity must be between 1 and 10")
    topology_id, window_end, targets = _load_topology(
        args.topology,
        expected_topology_id=args.expected_topology_id,
    )
    minimum_date = min((item.effective_from for item in targets), default=window_end)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            company_by_identity = _revalidate_targets(session, targets)
            company_ids = tuple(sorted(set(company_by_identity.values())))
            documents = _load_documents(
                session,
                company_ids,
                minimum_date=minimum_date,
                maximum_date=window_end,
            )
            session.rollback()
    finally:
        engine.dispose()

    evidence: list[SecTradingSymbolEvidence] = []
    observations: list[SecIdentityFilingObservation] = []
    fetch_cache: dict[int, FetchedFiling] = {}
    with SECClient.from_settings() as client:
        for target in targets:
            company_id = company_by_identity[target.identity_id]
            candidates = _candidate_documents(
                target,
                documents.get(company_id, ()),
                window_end=window_end,
                limit=args.max_filings_per_identity,
            )
            for document in candidates:
                fetched = fetch_cache.get(document.document_id)
                if fetched is None:
                    fetched = _fetch_filing(client, document)
                    fetch_cache[document.document_id] = fetched
                facts: list[tuple[str, str]] = []
                for symbol, concept, context_ref, source_url, payload_sha256 in fetched.symbols:
                    item = SecTradingSymbolEvidence(
                        row_id=target.identity_id,
                        cik=target.cik,
                        accession_number=document.accession_number,
                        filing_date=document.filing_date,
                        form_type=document.form_type,
                        symbol=symbol,
                        source_url=source_url,
                        payload_sha256=payload_sha256,
                        concept_name=concept,
                        context_ref=context_ref,
                    )
                    evidence.append(item)
                    facts.append((symbol, item.evidence_id))
                observations.append(
                    SecIdentityFilingObservation(
                        row_id=target.identity_id,
                        accession_number=document.accession_number,
                        filing_date=document.filing_date,
                        form_type=document.form_type,
                        facts=tuple(sorted(set(facts))),
                        inspected_urls=fetched.inspected_urls,
                        error=fetched.error,
                    )
                )

    decisions = plan_residual_sec_evidence(targets, tuple(observations))
    plan_id = residual_sec_plan_id(decisions, topology_id=topology_id)
    status_counts = Counter(item.status for item in decisions)
    payload = {
        "schema_version": RESIDUAL_SEC_EVIDENCE_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "topology_id": topology_id,
        "plan_id": plan_id,
        "target_count": len(targets),
        "candidate_document_count": sum(len(items) for items in documents.values()),
        "unique_filing_fetch_count": len(fetch_cache),
        "filing_observation_count": len(observations),
        "filing_error_count": sum(item.error is not None for item in observations),
        "sec_evidence_count": len(evidence),
        "status_counts": dict(sorted(status_counts.items())),
        "supported_count": sum(item.supported for item in decisions),
        "interpretation": (
            "Read-only exact-CIK SEC issuer-symbol evidence. Targets are frozen by the residual "
            "identity topology; filing evidence alone does not promote a row or establish its "
            "effective boundaries. Any fetch error or inspected symbol conflict fails closed."
        ),
        "targets": [item.as_dict() for item in targets],
        "evidence": [
            item.as_dict()
            for item in sorted(evidence, key=lambda candidate: candidate.evidence_id)
        ],
        "observations": [item.as_dict() for item in observations],
        "decisions": [item.as_dict() for item in decisions],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "topology_id": topology_id,
                "plan_id": plan_id,
                "target_count": len(targets),
                "supported_count": payload["supported_count"],
                "status_counts": payload["status_counts"],
                "unique_filing_fetch_count": len(fetch_cache),
                "filing_error_count": payload["filing_error_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
