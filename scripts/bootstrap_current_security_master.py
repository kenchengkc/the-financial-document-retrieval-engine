"""Bootstrap present-day stable securities for HU-2 without inferring historical membership."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import Security, SecurityIdentityPeriod

_BOOTSTRAP_SCHEMA_VERSION = "fdre-hu2-current-security-bootstrap-v1"
_BOOTSTRAP_SOURCE = "fdre-current-sp500-snapshot"
_BOOTSTRAP_VERIFICATION_STATUS = "provisional"
_BOOTSTRAP_CONFIDENCE = 0.90


@dataclass(frozen=True, slots=True)
class CurrentSecuritySeed:
    symbol: str
    primary_ticker: str
    source: str
    source_observed_at: datetime
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class CurrentSecurityBootstrapInput:
    source: str
    source_observed_at: datetime
    snapshot_sha256: str
    constituent_symbol_count: int
    seeds: tuple[CurrentSecuritySeed, ...]
    missing_catalog_symbols: tuple[str, ...]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def load_current_security_bootstrap(path: Path) -> CurrentSecurityBootstrapInput:
    """Parse the committed current-constituent snapshot into deterministic security seeds."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    aliases_raw = payload.get("aliases")
    primary_raw = payload.get("primary_tickers")
    missing_raw = payload.get("missing_from_catalog")
    source_raw = payload.get("source")
    generated_at_raw = payload.get("generated_at")

    if not isinstance(aliases_raw, dict) or not all(
        isinstance(symbol, str) and isinstance(primary, str)
        for symbol, primary in aliases_raw.items()
    ):
        raise ValueError("current constituent snapshot aliases must map strings to strings")
    if not isinstance(primary_raw, list) or not all(
        isinstance(item, str) for item in primary_raw
    ):
        raise ValueError("current constituent snapshot primary_tickers must be strings")
    if not isinstance(missing_raw, list) or not all(
        isinstance(item, str) for item in missing_raw
    ):
        raise ValueError("current constituent snapshot missing_from_catalog must be strings")
    if not isinstance(source_raw, str) or not source_raw.strip():
        raise ValueError("current constituent snapshot source is required")
    if not isinstance(generated_at_raw, str):
        raise ValueError("current constituent snapshot generated_at is required")

    normalized_aliases: dict[str, str] = {}
    for raw_symbol, raw_primary in aliases_raw.items():
        symbol = _normalize_symbol(raw_symbol)
        primary = _normalize_symbol(raw_primary)
        if not symbol or not primary:
            raise ValueError("current constituent symbols and primary tickers must be non-empty")
        previous = normalized_aliases.get(symbol)
        if previous is not None and previous != primary:
            raise ValueError(f"current constituent symbol {symbol} maps to multiple primaries")
        normalized_aliases[symbol] = primary

    primary_tickers = {_normalize_symbol(item) for item in primary_raw}
    alias_primary_tickers = set(normalized_aliases.values())
    if alias_primary_tickers != primary_tickers:
        raise ValueError("current constituent snapshot alias targets are inconsistent")

    missing_symbols = {_normalize_symbol(item) for item in missing_raw}
    constituent_symbols = set(normalized_aliases) | missing_symbols
    declared_constituent_count = int(payload.get("constituent_count", -1))
    declared_primary_count = int(payload.get("primary_ticker_count", -1))
    if len(constituent_symbols) != declared_constituent_count:
        raise ValueError("current constituent snapshot constituent_count is inconsistent")
    if len(primary_tickers) != declared_primary_count:
        raise ValueError("current constituent snapshot primary_ticker_count is inconsistent")

    source_observed_at = _parse_timestamp(generated_at_raw)
    snapshot_sha256 = _sha256_file(path)
    seeds = tuple(
        CurrentSecuritySeed(
            symbol=symbol,
            primary_ticker=primary,
            source=source_raw.strip(),
            source_observed_at=source_observed_at,
            snapshot_sha256=snapshot_sha256,
        )
        for symbol, primary in sorted(normalized_aliases.items())
    )
    return CurrentSecurityBootstrapInput(
        source=source_raw.strip(),
        source_observed_at=source_observed_at,
        snapshot_sha256=snapshot_sha256,
        constituent_symbol_count=len(constituent_symbols),
        seeds=seeds,
        missing_catalog_symbols=tuple(sorted(missing_symbols)),
    )


def _identity_source_hash(seed: CurrentSecuritySeed, company: Company) -> str:
    return _sha256_json(
        {
            "schema_version": _BOOTSTRAP_SCHEMA_VERSION,
            "snapshot_sha256": seed.snapshot_sha256,
            "source": seed.source,
            "source_observed_at": seed.source_observed_at.isoformat(),
            "symbol": seed.symbol,
            "primary_ticker": seed.primary_ticker,
            "company_cik": company.cik,
            "company_name": company.name,
            "company_exchange": company.exchange,
        }
    )


def _period_intersects_current_forward(period: SecurityIdentityPeriod, snapshot_date: date) -> bool:
    return period.effective_to is None or period.effective_to > snapshot_date


def bootstrap_current_security_master(
    session: Session,
    bootstrap: CurrentSecurityBootstrapInput,
    *,
    apply: bool,
) -> dict[str, object]:
    """Plan or apply the HU2-R0 current security-master bootstrap.

    Every mapped present-day constituent symbol becomes one stable common-stock security with a
    provisional identity period beginning on the snapshot date. Existing matching identities are
    reused. The function never creates universe memberships and never backdates current evidence.
    """

    snapshot_date = bootstrap.source_observed_at.date()
    companies = tuple(session.scalars(select(Company).order_by(Company.ticker, Company.id)))
    companies_by_ticker: dict[str, Company] = {}
    for company in companies:
        ticker = _normalize_symbol(company.ticker)
        if ticker in companies_by_ticker:
            raise ValueError(f"multiple production companies normalize to ticker {ticker}")
        companies_by_ticker[ticker] = company

    missing_primaries = sorted(
        {
            seed.primary_ticker
            for seed in bootstrap.seeds
            if seed.primary_ticker not in companies_by_ticker
        }
    )
    if missing_primaries:
        joined = ", ".join(missing_primaries)
        raise ValueError(
            "current snapshot primary tickers missing from production companies: " f"{joined}"
        )

    identity_rows = session.execute(
        select(SecurityIdentityPeriod, Security)
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .order_by(SecurityIdentityPeriod.symbol, SecurityIdentityPeriod.effective_from)
    ).all()
    identities_by_symbol: dict[str, list[tuple[SecurityIdentityPeriod, Security]]] = {}
    for period, security in identity_rows:
        if period.verification_status == "rejected":
            continue
        if not _period_intersects_current_forward(period, snapshot_date):
            continue
        identities_by_symbol.setdefault(_normalize_symbol(period.symbol), []).append(
            (period, security)
        )

    planned = 0
    created_securities = 0
    created_identities = 0
    reused_identities = 0
    for seed in bootstrap.seeds:
        company = companies_by_ticker[seed.primary_ticker]
        candidates = identities_by_symbol.get(seed.symbol, [])
        if candidates:
            if len(candidates) != 1:
                raise ValueError(
                    f"current symbol {seed.symbol} has multiple non-rejected identity periods "
                    "intersecting the snapshot-forward window"
                )
            period, security = candidates[0]
            if period.effective_from > snapshot_date:
                raise ValueError(
                    f"current symbol {seed.symbol} only has a future-dated identity period"
                )
            if security.company_id != company.id:
                raise ValueError(
                    f"current symbol {seed.symbol} resolves to the wrong production company"
                )
            if security.security_type != "common_stock":
                raise ValueError(
                    f"current symbol {seed.symbol} resolves to a non-common-stock security"
                )
            reused_identities += 1
            continue

        planned += 1
        if not apply:
            continue
        security = Security(
            company_id=company.id,
            security_type="common_stock",
            share_class=None,
        )
        session.add(security)
        session.flush()
        session.add(
            SecurityIdentityPeriod(
                security_id=security.id,
                symbol=seed.symbol,
                name=company.name,
                exchange=company.exchange,
                effective_from=snapshot_date,
                effective_to=None,
                source=_BOOTSTRAP_SOURCE,
                source_url=None,
                source_observed_at=bootstrap.source_observed_at,
                source_hash=_identity_source_hash(seed, company),
                verification_status=_BOOTSTRAP_VERIFICATION_STATUS,
                confidence=_BOOTSTRAP_CONFIDENCE,
            )
        )
        created_securities += 1
        created_identities += 1

    return {
        "schema_version": _BOOTSTRAP_SCHEMA_VERSION,
        "applied": apply,
        "snapshot_source": bootstrap.source,
        "snapshot_generated_at": bootstrap.source_observed_at.isoformat(),
        "snapshot_sha256": bootstrap.snapshot_sha256,
        "constituent_symbol_count": bootstrap.constituent_symbol_count,
        "mapped_symbol_count": len(bootstrap.seeds),
        "missing_catalog_symbols": list(bootstrap.missing_catalog_symbols),
        "planned_security_count": planned,
        "created_security_count": created_securities,
        "created_identity_period_count": created_identities,
        "reused_identity_period_count": reused_identities,
        "identity_effective_from": snapshot_date.isoformat(),
        "identity_verification_status": _BOOTSTRAP_VERIFICATION_STATUS,
        "identity_confidence": _BOOTSTRAP_CONFIDENCE,
        "historical_memberships_written": 0,
        "interpretation": (
            "Present-day security identities only. This bootstrap does not establish any "
            "historical membership or pre-snapshot ticker interval."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply the HU-2 current security-master bootstrap."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--current-constituents",
        type=Path,
        default=Path("data/sample/sp500_tickers.json"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bootstrap = load_current_security_bootstrap(args.current_constituents)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            report = bootstrap_current_security_master(session, bootstrap, apply=bool(args.apply))
            if args.apply:
                session.commit()
            else:
                session.rollback()
    finally:
        engine.dispose()

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
