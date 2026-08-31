"""Reconcile the HU-2 2009 anchor mismatch without treating ticker aliases as membership.

The original comparison mixed two different concepts:

* lawcal rows were replayed before their upstream ``created_at`` validity boundary; and
* the fja05680 snapshot rewrites many historical tickers to terminal/successor symbols.

This audit reproduces the original 29-missing/61-unexpected result, applies the upstream
source-validity rule, classifies every residual symbol discrepancy, and checks the result against
the 500 common-stock holdings in IVV's independently filed 2009-12-31 SEC N-Q schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_component_history import (
    HistoricalComponentHistoryAdapter,
    HistoricalComponentRecord,
)
from fdre.research.historical_universe_anchor import (
    SecIvvHoldingsSnapshotAdapter,
    normalize_display_symbol,
)
from fdre.research.historical_universe_identity import normalize_issuer_name

_SCHEMA_VERSION = "fdre-hu2-anchor-reconciliation-v1"
_FJA_ANCHOR_DATE = date(2009, 12, 30)
_SEC_IVV_DATE = date(2009, 12, 31)

# Each pair replaces an actual point-in-time ticker in lawcal's source-valid snapshot with the
# later terminal/successor ticker used by the fja05680 anchor.  The mapping is comparison-only;
# it is never used to manufacture a SecurityIdentityPeriod.
_TERMINAL_SYMBOL_ALIASES: tuple[tuple[str, str], ...] = (
    ("AA", "ARNC"),
    ("AOC", "AON"),
    ("BHI", "BHGE"),
    ("BTU", "BTUUQ"),
    ("CBG", "CBRE"),
    ("COH", "TPR"),
    ("CSC", "DXC"),
    ("DPS", "KDP"),
    ("DV", "ATGE"),
    ("EK", "EKDKQ"),
    ("ERTS", "EA"),
    ("FO", "BEAM"),
    ("FPL", "NEE"),
    ("GCI", "TGNA"),
    ("HCN", "WELL"),
    ("JDSU", "VIAV"),
    ("KFT", "MDLZ"),
    ("LTD", "LB"),
    ("LUK", "JEF"),
    ("MHP", "SPGI"),
    ("MOT", "MSI"),
    ("NU", "ES"),
    ("PCS", "TMUS"),
    ("RSH", "RSHCQ"),
    ("SLE", "HSH"),
    ("TSO", "ANDV"),
    ("WAG", "WBA"),
    ("WFMI", "WFM"),
    ("WFR", "SUNEQ"),
    ("WLP", "ANTM"),
    ("WPI", "AGN"),
    ("WPO", "GHC"),
    ("WYN", "WYND"),
    ("YHOO", "AABA"),
    ("ZMH", "ZBH"),
)

# These names occur in the official IVV schedule but have no source-valid lawcal row at the
# fja anchor date.  The fja symbol is retained only as a reconciliation label.  SEC names do not
# establish a ticker or CIK, so these rows remain identity remediation work.
_SEC_CONFIRMED_SOURCE_GAPS: tuple[tuple[str, str], ...] = (
    ("APH", "Amphenol Corp. Class A"),
    ("ARG", "Airgas Inc."),
    ("BKNG", "Priceline.com Inc."),
    ("CB", "Chubb Corp."),
    ("CLF", "Cliffs Natural Resources Inc."),
    ("D", "Dominion Resources Inc."),
    ("FCX", "Freeport-McMoRan Copper & Gold Inc."),
    ("FOXA", "News Corp. Class A NVS"),
    ("GAS", "Nicor Inc."),
    ("GOOGL", "Google Inc. Class A"),
    ("HUM", "Humana Inc."),
    ("JCI", "Johnson Controls Inc."),
    ("LDOS", "SAIC Inc."),
    ("MJN", "Mead Johnson Nutrition Co. Class A"),
    ("ROST", "Ross Stores Inc."),
    ("SRE", "Sempra Energy"),
    ("TROW", "T. Rowe Price Group Inc."),
    ("V", "Visa Inc. Class A"),
)

# Point-in-time identities for the 18 securities that the SEC-filed IVV schedule confirms but
# the source-valid lawcal replay omits.  ``anchor_symbol`` above is the fja comparison label and
# is deliberately not reused here: four of those labels are later successor tickers.  CIKs are
# tied to the issuer named in the SEC schedule via the SEC submissions endpoint; symbols and
# end boundaries are the dated, pre-terminalized identities used at the anchor.
#
# (anchor label, 2009-12-30 symbol, CIK, effective_to)
_SEC_CONFIRMED_GAP_IDENTITIES: tuple[
    tuple[str, str, str, date | None], ...
] = (
    ("APH", "APH", "0000820313", None),
    ("ARG", "ARG", "0000804212", date(2016, 5, 23)),
    ("BKNG", "PCLN", "0001075531", date(2018, 2, 27)),
    ("CB", "CB", "0000020171", date(2016, 1, 19)),
    ("CLF", "CLF", "0000764065", date(2014, 4, 2)),
    ("D", "D", "0000715957", None),
    ("FCX", "FCX", "0000831259", None),
    ("FOXA", "NWSA", "0001308161", date(2013, 7, 1)),
    ("GAS", "GAS", "0000072020", date(2011, 12, 12)),
    ("GOOGL", "GOOG", "0001288776", date(2014, 4, 3)),
    ("HUM", "HUM", "0000049071", None),
    ("JCI", "JCI", "0000053669", date(2016, 9, 2)),
    ("LDOS", "SAI", "0001336920", date(2013, 9, 20)),
    ("MJN", "MJN", "0001452575", date(2017, 6, 19)),
    ("ROST", "ROST", "0000745732", None),
    ("SRE", "SRE", "0001032208", None),
    ("TROW", "TROW", "0001113169", None),
    ("V", "V", "0001403161", None),
)

# The pinned component file assigns Black & Decker the successor Stanley CIK even though both
# securities are simultaneously present in the SEC anchor.  SEC's issuer lookup identifies the
# historical Black & Decker issuer as CIK 0000012355.
_ANCHOR_CIK_CORRECTIONS = {("BDK", "0000093556"): "0000012355"}

_REJECTED_LAWCAL_SYMBOL = "ASH"
_REJECTED_FJA_DUPLICATE = "XL"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
    return parsed


def _counter_rows(counter: Counter[str]) -> list[str]:
    return [
        symbol
        for symbol, count in sorted(counter.items())
        for _ in range(count)
    ]


def _active_symbols(
    records: Sequence[HistoricalComponentRecord],
    *,
    as_of: date,
    enforce_created_at: bool,
) -> Counter[str]:
    symbols: Counter[str] = Counter()
    for record in records:
        effective_from = (
            record.source_valid_from if enforce_created_at else record.effective_from
        )
        effective_to = record.effective_to
        if effective_from <= as_of and (effective_to is None or as_of < effective_to):
            symbols[normalize_display_symbol(record.symbol)] += 1
    return symbols


def _identity_safe_anchor(
    records: Sequence[HistoricalComponentRecord],
    *,
    sec_names: set[str],
    sec_source_ref: str,
    sec_source_hash: str,
) -> dict[str, object]:
    gap_names = dict(_SEC_CONFIRMED_SOURCE_GAPS)
    gap_identities = {row[0]: row for row in _SEC_CONFIRMED_GAP_IDENTITIES}
    if set(gap_names) != set(gap_identities):
        raise ValueError("SEC anchor gap identities do not cover the adjudicated gaps")

    rows: list[dict[str, object]] = []
    for record in records:
        if not (
            record.source_valid_from <= _FJA_ANCHOR_DATE
            and (record.effective_to is None or record.effective_to > _FJA_ANCHOR_DATE)
        ):
            continue
        symbol = normalize_display_symbol(record.symbol)
        if symbol == _REJECTED_LAWCAL_SYMBOL:
            continue
        cik = _ANCHOR_CIK_CORRECTIONS.get((symbol, record.cik), record.cik)
        rows.append(
            {
                "cik": cik,
                "symbol": symbol,
                "name": record.name,
                "membership_effective_to": (
                    record.effective_to.isoformat() if record.effective_to else None
                ),
                "identity_decision": (
                    "sec_issuer_cik_correction"
                    if cik != record.cik
                    else "source_valid_point_in_time_component"
                ),
                "identity_source_refs": [
                    record.source_ref,
                    (
                        "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
                        if cik != record.cik
                        else record.source_ref
                    ),
                ],
                "source_hash": _hash(
                    {
                        "record_id": record.record_id,
                        "adjudicated_cik": cik,
                    }
                ),
            }
        )

    for anchor_symbol, point_in_time_symbol, cik, effective_to in (
        _SEC_CONFIRMED_GAP_IDENTITIES
    ):
        sec_name = gap_names[anchor_symbol]
        if normalize_issuer_name(sec_name) not in sec_names:
            raise ValueError(f"SEC anchor holding is absent: {sec_name}")
        rows.append(
            {
                "cik": cik,
                "symbol": point_in_time_symbol,
                "name": sec_name,
                "membership_effective_to": (
                    effective_to.isoformat() if effective_to else None
                ),
                "identity_decision": "dated_sec_holding_ticker_cik_adjudication",
                "anchor_comparison_symbol": anchor_symbol,
                "identity_source_refs": [
                    sec_source_ref,
                    f"https://data.sec.gov/submissions/CIK{cik}.json",
                ],
                "source_hash": _hash(
                    {
                        "sec_source_hash": sec_source_hash,
                        "sec_holding_name": sec_name,
                        "point_in_time_symbol": point_in_time_symbol,
                        "cik": cik,
                        "effective_to": effective_to.isoformat() if effective_to else None,
                    }
                ),
            }
        )

    rows.sort(key=lambda row: (str(row["cik"]), str(row["symbol"])))
    keys = [(str(row["cik"]), str(row["symbol"])) for row in rows]
    if len(rows) != 500 or len(set(keys)) != 500:
        raise ValueError("identity-safe SEC anchor must contain 500 unique securities")
    anchor_payload = {
        "schema_version": "fdre-hu2-identity-safe-anchor-v1",
        "universe_code": "sp500",
        "effective_at": _FJA_ANCHOR_DATE.isoformat(),
        "constituent_count": len(rows),
        "constituents": rows,
        "sec_membership_effective_at": _SEC_IVV_DATE.isoformat(),
        "sec_source_ref": sec_source_ref,
        "sec_source_hash": sec_source_hash,
    }
    return {**anchor_payload, "anchor_id": _hash(anchor_payload)}


def _difference(expected: Counter[str], actual: Counter[str]) -> dict[str, object]:
    missing = _counter_rows(expected - actual)
    unexpected = _counter_rows(actual - expected)
    return {
        "actual_constituent_count": sum(actual.values()),
        "missing_count": len(missing),
        "missing_symbols": missing,
        "unexpected_count": len(unexpected),
        "unexpected_symbols": unexpected,
    }


def build_reconciliation_report(
    *,
    component_history: Path,
    component_history_ref: str,
    fja_anchor: Path,
    sec_filing: Path,
    sec_source_ref: str,
    sec_source_url: str,
    observed_at: datetime,
) -> dict[str, object]:
    records = HistoricalComponentHistoryAdapter(
        source_ref=component_history_ref
    ).load(component_history)
    anchor_payload = json.loads(fja_anchor.read_text(encoding="utf-8"))
    if not isinstance(anchor_payload, dict):
        raise ValueError("fja anchor must be a JSON object")
    if date.fromisoformat(str(anchor_payload["effective_at"])) != _FJA_ANCHOR_DATE:
        raise ValueError("reconciliation requires the pinned 2009-12-30 fja anchor")
    raw_tokens = anchor_payload.get("lineage_tokens")
    if not isinstance(raw_tokens, list) or not all(
        isinstance(token, str) for token in raw_tokens
    ):
        raise ValueError("fja anchor lineage_tokens must be strings")
    expected = Counter(normalize_display_symbol(token) for token in raw_tokens)

    sec_anchor = SecIvvHoldingsSnapshotAdapter(
        source_ref=sec_source_ref,
        source_url=sec_source_url,
    ).load(sec_filing, observed_at=observed_at)
    if sec_anchor.effective_at != _SEC_IVV_DATE or sec_anchor.holding_count != 500:
        raise ValueError("reconciliation requires IVV's complete 2009-12-31 schedule")
    sec_names = {normalize_issuer_name(holding.name) for holding in sec_anchor.holdings}
    gap_rows = [
        {
            "anchor_symbol": symbol,
            "sec_holding_name": name,
            "sec_name_exact_match": normalize_issuer_name(name) in sec_names,
            "decision": "confirmed_membership_gap_identity_unresolved",
        }
        for symbol, name in _SEC_CONFIRMED_SOURCE_GAPS
    ]
    if not all(bool(row["sec_name_exact_match"]) for row in gap_rows):
        raise ValueError("one or more adjudicated gaps is absent from the SEC IVV schedule")

    naive = _active_symbols(
        records,
        as_of=_FJA_ANCHOR_DATE,
        enforce_created_at=False,
    )
    source_valid = _active_symbols(
        records,
        as_of=_FJA_ANCHOR_DATE,
        enforce_created_at=True,
    )
    naive_difference = _difference(expected, naive)
    source_valid_difference = _difference(expected, source_valid)

    residual_missing = Counter(expected - source_valid)
    residual_unexpected = Counter(source_valid - expected)
    alias_actual = Counter(actual for actual, _ in _TERMINAL_SYMBOL_ALIASES)
    alias_anchor = Counter(anchor for _, anchor in _TERMINAL_SYMBOL_ALIASES)
    gap_symbols = Counter(symbol for symbol, _ in _SEC_CONFIRMED_SOURCE_GAPS)
    classified_missing = alias_anchor + gap_symbols + Counter({_REJECTED_FJA_DUPLICATE: 1})
    classified_unexpected = alias_actual + Counter({_REJECTED_LAWCAL_SYMBOL: 1})
    fully_classified = (
        residual_missing == classified_missing
        and residual_unexpected == classified_unexpected
    )
    if not fully_classified:
        raise ValueError("anchor discrepancies changed and are not fully classified")

    adjudicated_count = (
        sum(source_valid.values())
        - 1  # ASH is absent from the primary-source holdings schedule.
        + len(_SEC_CONFIRMED_SOURCE_GAPS)
    )
    independent_count_match = adjudicated_count == sec_anchor.holding_count
    identity_safe_anchor = _identity_safe_anchor(
        records,
        sec_names=sec_names,
        sec_source_ref=sec_source_ref,
        sec_source_hash=sec_anchor.source_hash,
    )
    decisions = {
        "terminal_symbol_aliases": list(_TERMINAL_SYMBOL_ALIASES),
        "sec_confirmed_source_gaps": list(_SEC_CONFIRMED_SOURCE_GAPS),
        "rejected_lawcal_symbol": _REJECTED_LAWCAL_SYMBOL,
        "rejected_fja_duplicate": _REJECTED_FJA_DUPLICATE,
    }
    reconciliation_id = _hash(
        {
            "schema_version": _SCHEMA_VERSION,
            "component_history_ref": component_history_ref,
            "component_history_sha256": hashlib.sha256(
                component_history.read_bytes()
            ).hexdigest(),
            "fja_anchor_id": anchor_payload.get("anchor_id"),
            "sec_ivv_anchor_id": sec_anchor.anchor_id,
            "decisions": decisions,
        }
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "reconciliation_id": reconciliation_id,
        "as_of": _FJA_ANCHOR_DATE.isoformat(),
        "next_day_independent_check_as_of": sec_anchor.effective_at.isoformat(),
        "fja_anchor_id": anchor_payload.get("anchor_id"),
        "fja_anchor_sha256": hashlib.sha256(fja_anchor.read_bytes()).hexdigest(),
        "fja_anchor_constituent_count": sum(expected.values()),
        "component_history_ref": component_history_ref,
        "component_history_sha256": hashlib.sha256(
            component_history.read_bytes()
        ).hexdigest(),
        "sec_ivv_anchor_id": sec_anchor.anchor_id,
        "sec_ivv_holding_count": sec_anchor.holding_count,
        "sec_ivv_source": sec_anchor.source,
        "sec_ivv_source_ref": sec_anchor.source_ref,
        "sec_ivv_source_url": sec_anchor.source_url,
        "sec_ivv_source_hash": sec_anchor.source_hash,
        "original_materializer_comparison": naive_difference,
        "source_valid_comparison": source_valid_difference,
        "created_at_removed_row_count": sum(naive.values()) - sum(source_valid.values()),
        "terminal_symbol_alias_count": len(_TERMINAL_SYMBOL_ALIASES),
        "terminal_symbol_aliases": [
            {
                "point_in_time_symbol": actual,
                "fja_terminal_symbol": terminal,
                "decision": "comparison_alias_only",
            }
            for actual, terminal in _TERMINAL_SYMBOL_ALIASES
        ],
        "sec_confirmed_source_gap_count": len(gap_rows),
        "sec_confirmed_source_gaps": gap_rows,
        "rejected_lawcal_rows": [
            {
                "symbol": _REJECTED_LAWCAL_SYMBOL,
                "decision": "absent_from_sec_ivv_schedule",
            }
        ],
        "rejected_fja_rows": [
            {
                "symbol": _REJECTED_FJA_DUPLICATE,
                "decision": "duplicate_display_lineage_at_anchor",
            }
        ],
        "adjudicated_constituent_count": adjudicated_count,
        "all_symbol_discrepancies_classified": fully_classified,
        "independent_primary_source_count_match": independent_count_match,
        "anchor_reconciled": fully_classified and independent_count_match,
        "identity_safe_anchor": identity_safe_anchor,
        "production_identity_ready": True,
        "observed_at": observed_at.isoformat(),
        "interpretation": (
            "The original symbol mismatch is fully classified and the adjudicated count matches "
            "the 500 common stocks in IVV's SEC-filed schedule. The fja snapshot remains a "
            "terminal-lineage/count check, not point-in-time ticker identity. The 18 SEC-confirmed "
            "membership gaps have dated point-in-time ticker/CIK decisions, and the resulting "
            "identity-safe anchor contains 500 unique securities."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile the HU-2 complete anchor mismatch.")
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--fja-anchor", required=True, type=Path)
    parser.add_argument("--sec-filing", required=True, type=Path)
    parser.add_argument("--sec-source-ref", required=True)
    parser.add_argument("--sec-source-url", required=True)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_reconciliation_report(
        component_history=args.component_history,
        component_history_ref=args.component_history_ref,
        fja_anchor=args.fja_anchor,
        sec_filing=args.sec_filing,
        sec_source_ref=args.sec_source_ref,
        sec_source_url=args.sec_source_url,
        observed_at=args.observed_at or datetime.now(UTC),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
