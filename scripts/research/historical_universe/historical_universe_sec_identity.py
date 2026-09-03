"""Project HU issuer→symbol closure from immutable SEC filing-level XBRL evidence.

The command is read-only. It combines the existing pinned ticker-state containment decision with
an explicit ``dei:TradingSymbol`` fact fetched from a filing belonging to the exact SEC issuer CIK.
No membership or identity row is mutated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.ingestion.sec_client import SECClient
from fdre.research.historical_universe_lineage import (
    TickerMembershipLineageAdapter,
    normalize_symbol,
)
from fdre.research.historical_universe_sec_identity import (
    SecIdentityFilingObservation,
    SecTradingSymbolEvidence,
    extract_trading_symbols,
    filing_directory_index_url,
    plan_sec_identity_support,
    sec_identity_plan_id,
    xbrl_instance_filenames,
)
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    plan_state_support,
)


@dataclass(frozen=True, slots=True)
class IdentityTarget:
    interval: ProvisionalStateInterval
    company_id: int


@dataclass(frozen=True, slots=True)
class CandidateDocument:
    document_id: int
    company_id: int
    accession_number: str
    filing_date: date
    form_type: str
    primary_document_url: str


@dataclass(frozen=True, slots=True)
class FetchedFiling:
    symbols: tuple[tuple[str, str, str | None, str, str], ...]
    inspected_urls: tuple[str, ...]
    error: str | None = None


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _load_targets(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> tuple[IdentityTarget, ...]:
    security_ids = tuple(
        sorted(
            {
                int(value)
                for value in session.scalars(
                    select(UniverseMembership.security_id).where(
                        UniverseMembership.universe_code == universe_code,
                        UniverseMembership.verification_status != "rejected",
                        UniverseMembership.effective_from <= window_end,
                        (
                            UniverseMembership.effective_to.is_(None)
                            | (UniverseMembership.effective_to > window_start)
                        ),
                    )
                )
            }
        )
    )
    if not security_ids:
        return ()
    rows = session.execute(
        select(
            SecurityIdentityPeriod.id,
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.source,
            SecurityIdentityPeriod.source_hash,
            Company.id.label("company_id"),
            Company.cik,
        )
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            SecurityIdentityPeriod.security_id.in_(security_ids),
            SecurityIdentityPeriod.verification_status == "provisional",
            SecurityIdentityPeriod.effective_from <= window_end,
            (
                SecurityIdentityPeriod.effective_to.is_(None)
                | (SecurityIdentityPeriod.effective_to > window_start)
            ),
        )
        .order_by(
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.id,
        )
    ).all()
    return tuple(
        IdentityTarget(
            interval=ProvisionalStateInterval(
                row_kind="identity",
                row_id=int(row.id),
                security_id=int(row.security_id),
                cik=str(row.cik),
                symbol=normalize_symbol(str(row.symbol)),
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                source=str(row.source),
                source_hash=str(row.source_hash),
            ),
            company_id=int(row.company_id),
        )
        for row in rows
    )


def _load_documents(
    session: Session,
    targets: tuple[IdentityTarget, ...],
    *,
    window_start: date,
    window_end: date,
) -> dict[int, tuple[CandidateDocument, ...]]:
    company_ids = tuple(sorted({target.company_id for target in targets}))
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
            Document.form_type.in_(["10-K", "10-Q"]),
            Document.is_amendment.is_(False),
            Document.filing_date.is_not(None),
            Document.filing_date >= window_start,
            Document.filing_date <= window_end,
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
    return {
        company_id: tuple(documents)
        for company_id, documents in sorted(grouped.items())
    }


def _candidate_documents(
    target: IdentityTarget,
    documents: dict[int, tuple[CandidateDocument, ...]],
    *,
    window_end: date,
    limit: int,
) -> tuple[CandidateDocument, ...]:
    interval = target.interval
    upper = interval.effective_to or (window_end + date.resolution)
    eligible = [
        document
        for document in documents.get(target.company_id, ())
        if interval.effective_from <= document.filing_date < upper
    ]
    # Prefer annual filings, then the most recent filings inside the asserted identity interval.
    eligible.sort(
        key=lambda item: (
            0 if item.form_type == "10-K" else 1,
            -item.filing_date.toordinal(),
            item.accession_number,
        )
    )
    return tuple(eligible[:limit])


def _payload_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fetch_filing(client: SECClient, document: CandidateDocument) -> FetchedFiling:
    inspected: list[str] = []
    try:
        primary = client.get_bytes(document.primary_document_url)
        inspected.append(document.primary_document_url)
        primary_hash = _payload_hash(primary)
        facts = extract_trading_symbols(primary)
        if facts:
            return FetchedFiling(
                symbols=tuple(
                    (symbol, concept, context_ref, document.primary_document_url, primary_hash)
                    for symbol, concept, context_ref in facts
                ),
                inspected_urls=tuple(inspected),
            )

        index_url = filing_directory_index_url(document.primary_document_url)
        index_payload = client.get_json(index_url)
        inspected.append(index_url)
        base_url = index_url.rsplit("/", 1)[0]
        for filename in xbrl_instance_filenames(index_payload)[:3]:
            source_url = f"{base_url}/{quote(filename)}"
            payload = client.get_bytes(source_url)
            inspected.append(source_url)
            payload_hash = _payload_hash(payload)
            facts = extract_trading_symbols(payload)
            if facts:
                return FetchedFiling(
                    symbols=tuple(
                        (symbol, concept, context_ref, source_url, payload_hash)
                        for symbol, concept, context_ref in facts
                    ),
                    inspected_urls=tuple(inspected),
                )
        return FetchedFiling(symbols=(), inspected_urls=tuple(inspected))
    except Exception as exc:  # network/source failures stay non-promotable and auditable
        return FetchedFiling(
            symbols=(),
            inspected_urls=tuple(inspected),
            error=f"{type(exc).__name__}: {exc}",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project SEC filing-level issuer→symbol support for provisional HU identities."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--ticker-lineages", required=True, type=Path)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--max-filings-per-identity", type=int, default=2)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_filings_per_identity < 1 or args.max_filings_per_identity > 5:
        raise ValueError("--max-filings-per-identity must be between 1 and 5")
    universe_code = args.universe_code.strip().lower()
    lineages = TickerMembershipLineageAdapter(source_ref=args.ticker_lineages_ref).load(
        args.ticker_lineages
    )

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            targets = _load_targets(
                session,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            documents = _load_documents(
                session,
                targets,
                window_start=args.window_start,
                window_end=args.window_end,
            )
    finally:
        engine.dispose()

    intervals = tuple(target.interval for target in targets)
    state_decisions = plan_state_support(intervals, lineages)
    state_by_row = {decision.row_id: decision for decision in state_decisions}

    evidence: list[SecTradingSymbolEvidence] = []
    observations: list[SecIdentityFilingObservation] = []
    fetch_cache: dict[int, FetchedFiling] = {}
    with SECClient.from_settings() as client:
        for target in targets:
            state = state_by_row.get(target.interval.row_id)
            if state is None or state.status != "fully_supported":
                continue
            candidates = _candidate_documents(
                target,
                documents,
                window_end=args.window_end,
                limit=args.max_filings_per_identity,
            )
            for document in candidates:
                fetched = fetch_cache.get(document.document_id)
                if fetched is None:
                    fetched = _fetch_filing(client, document)
                    fetch_cache[document.document_id] = fetched
                fact_pairs: list[tuple[str, str]] = []
                for symbol, concept, context_ref, source_url, payload_sha256 in fetched.symbols:
                    item = SecTradingSymbolEvidence(
                        row_id=target.interval.row_id,
                        cik=target.interval.cik,
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
                    fact_pairs.append((symbol, item.evidence_id))
                observations.append(
                    SecIdentityFilingObservation(
                        row_id=target.interval.row_id,
                        accession_number=document.accession_number,
                        filing_date=document.filing_date,
                        form_type=document.form_type,
                        facts=tuple(sorted(set(fact_pairs))),
                        inspected_urls=fetched.inspected_urls,
                        error=fetched.error,
                    )
                )

    decisions = plan_sec_identity_support(
        intervals,
        state_decisions,
        tuple(observations),
    )
    plan_id = sec_identity_plan_id(decisions)
    status_counts = Counter(item.status for item in decisions)
    state_status_counts = Counter(item.status for item in state_decisions)
    errors = [item for item in observations if item.error is not None]
    payload = {
        "schema_version": "fdre-hu-sec-identity-projection-v1",
        "mode": "projection",
        "applied": False,
        "plan_id": plan_id,
        "universe_code": universe_code,
        "window_start": args.window_start.isoformat(),
        "window_end": args.window_end.isoformat(),
        "ticker_lineages_ref": args.ticker_lineages_ref,
        "ticker_lineage_count": len(lineages),
        "provisional_identity_count": len(intervals),
        "state_status_counts": dict(sorted(state_status_counts.items())),
        "candidate_document_count": sum(len(items) for items in documents.values()),
        "unique_filing_fetch_count": len(fetch_cache),
        "filing_observation_count": len(observations),
        "filing_error_count": len(errors),
        "sec_evidence_count": len(evidence),
        "status_counts": dict(sorted(status_counts.items())),
        "promotion_candidate_count": sum(item.promotion_candidate for item in decisions),
        "interpretation": (
            "Projection only. A promotion candidate requires exact full-interval support from one "
            "pinned ticker-state lineage plus an immutable SEC filing fetched under the exact CIK "
            "that explicitly reports the same dei:TradingSymbol. Conflicts, missing SEC facts, "
            "partial ticker-state overlaps, and all date disagreements remain provisional."
        ),
        "evidence": [
            item.as_dict()
            for item in sorted(evidence, key=lambda item: item.evidence_id)
        ],
        "observations": [item.as_dict() for item in observations],
        "decisions": [item.as_dict() for item in decisions],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": plan_id,
                "provisional_identity_count": len(intervals),
                "promotion_candidate_count": payload["promotion_candidate_count"],
                "status_counts": payload["status_counts"],
                "unique_filing_fetch_count": len(fetch_cache),
                "filing_error_count": len(errors),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
