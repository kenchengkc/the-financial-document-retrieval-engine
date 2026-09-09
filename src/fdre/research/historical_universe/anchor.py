"""Independent complete-snapshot anchors for Historical Universe HU-2.

The initial anchor adapter targets the public fja05680/sp500 historical component file. That
source encodes ticker-reuse lineage with terminal ``-YYYYMM`` suffixes. Those lineage tokens are
preserved as source identity; a separate display symbol is exposed for comparison only.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

_LINEAGE_SUFFIX = re.compile(r"^(?P<symbol>.+)-(?P<end_yyyymm>\d{6})$")
_ANCHOR_SCHEMA_VERSION = "fdre-hu2-complete-snapshot-anchor-v1"
_SEC_HOLDINGS_SCHEMA_VERSION = "fdre-hu2-sec-fund-holdings-anchor-v1"
_TRAILING_FOOTNOTES = re.compile(r"(?:\([a-z](?:,[a-z])?\))+$", re.IGNORECASE)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_display_symbol(value: str) -> str:
    """Normalize a source ticker for display without discarding lineage identity."""

    token = value.strip().upper()
    match = _LINEAGE_SUFFIX.fullmatch(token)
    if match is not None:
        token = match.group("symbol")
    return token.replace(".", "-")


@dataclass(frozen=True, slots=True)
class CompleteSnapshotConstituent:
    lineage_token: str
    display_symbol: str
    lineage_end_yyyymm: str | None


@dataclass(frozen=True, slots=True)
class CompleteUniverseSnapshotAnchor:
    universe_code: str
    effective_at: date
    constituents: tuple[CompleteSnapshotConstituent, ...]
    source: str
    source_url: str
    source_ref: str
    source_observed_at: datetime
    source_hash: str

    @property
    def constituent_count(self) -> int:
        return len(self.constituents)

    @property
    def duplicate_display_symbols(self) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for item in self.constituents:
            counts[item.display_symbol] = counts.get(item.display_symbol, 0) + 1
        return tuple(sorted(symbol for symbol, count in counts.items() if count > 1))

    @property
    def anchor_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _ANCHOR_SCHEMA_VERSION,
                "universe_code": self.universe_code,
                "effective_at": self.effective_at.isoformat(),
                "lineage_tokens": [item.lineage_token for item in self.constituents],
                "source": self.source,
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class OfficialFundHolding:
    """One security name exactly as reported in a filed fund schedule."""

    name: str


@dataclass(frozen=True, slots=True)
class OfficialFundHoldingsAnchor:
    """A complete primary-source fund holding schedule used as an external check."""

    fund_name: str
    effective_at: date
    holdings: tuple[OfficialFundHolding, ...]
    source: str
    source_url: str
    source_ref: str
    source_observed_at: datetime
    source_hash: str

    @property
    def holding_count(self) -> int:
        return len(self.holdings)

    @property
    def anchor_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _SEC_HOLDINGS_SCHEMA_VERSION,
                "fund_name": self.fund_name,
                "effective_at": self.effective_at.isoformat(),
                "holding_names": [holding.name for holding in self.holdings],
                "source": self.source,
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            }
        )


class SecIvvHoldingsSnapshotAdapter:
    """Parse IVV's common-stock schedule from one pinned SEC N-Q filing.

    The 2009-12-31 iShares S&P 500 Index Fund schedule is a primary-source,
    independently filed complete holdings check.  It contains issuer/security names but
    no point-in-time tickers or CIKs, so it can adjudicate anchor membership and count
    discrepancies without silently becoming identity evidence.
    """

    source_name = "sec-edgar-ishares-ivv-nq"
    fund_name = "iShares S&P 500 Index Fund"
    _fund_marker = "S&amp;P 500 INDEX FUND"

    def __init__(self, *, source_ref: str, source_url: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required for a pinned SEC filing")
        if not source_url.strip():
            raise ValueError("source_url is required")
        self.source_ref = source_ref.strip()
        self.source_url = source_url.strip()

    @staticmethod
    def _security_name(value: str) -> str:
        normalized = " ".join(html.unescape(value).replace("\xa0", " ").split())
        return _TRAILING_FOOTNOTES.sub("", normalized).strip()

    def load(
        self,
        path: Path,
        *,
        observed_at: datetime,
    ) -> OfficialFundHoldingsAnchor:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        source_bytes = path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        raw_html = source_bytes.decode("utf-8", errors="replace")
        marker_at = raw_html.find(self._fund_marker)
        if marker_at < 0:
            raise ValueError("could not find the IVV fund schedule in the SEC filing")
        schedule_at = raw_html.rfind("Schedule of Investments", 0, marker_at)
        common_stock_end = raw_html.find("TOTAL COMMON STOCKS", marker_at)
        if schedule_at < 0 or common_stock_end < 0:
            raise ValueError("could not bound IVV common-stock holdings in the SEC filing")

        fragment = raw_html[schedule_at:common_stock_end]
        fragment_text = " ".join(BeautifulSoup(fragment, "html.parser").stripped_strings)
        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|"
            r"November|December)\s+(\d{1,2}),\s+(\d{4})",
            fragment_text,
        )
        if date_match is None:
            raise ValueError("could not parse the IVV holdings effective date")
        effective_at = datetime.strptime(date_match.group(0), "%B %d, %Y").date()

        soup = BeautifulSoup(fragment, "html.parser")
        holding_names: list[str] = []
        for row in soup.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            name_cell = cells[0]
            if name_cell.find("b") is not None:
                continue
            name = self._security_name(" ".join(name_cell.stripped_strings))
            if not name:
                continue
            numeric_cells = 0
            for cell in cells[1:]:
                value = "".join(cell.stripped_strings)
                value = value.replace(",", "").replace("$", "").replace("—", "")
                if value.isdigit():
                    numeric_cells += 1
            if numeric_cells >= 2:
                holding_names.append(name)

        if len(holding_names) != len(set(holding_names)):
            raise ValueError("IVV common-stock schedule contains duplicate holding names")
        if not 490 <= len(holding_names) <= 510:
            raise ValueError(
                "IVV common-stock schedule has implausible holding count: "
                f"{len(holding_names)}"
            )
        return OfficialFundHoldingsAnchor(
            fund_name=self.fund_name,
            effective_at=effective_at,
            holdings=tuple(OfficialFundHolding(name=name) for name in holding_names),
            source=self.source_name,
            source_url=self.source_url,
            source_ref=self.source_ref,
            source_observed_at=observed_at,
            source_hash=source_hash,
        )


class HistoricalComponentsSnapshotAdapter:
    """Read one complete point-in-time snapshot from the fja05680/sp500 CSV."""

    source_name = "fja05680/sp500-historical-components"

    def __init__(self, *, source_ref: str, source_url: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required for a pinned anchor")
        if not source_url.strip():
            raise ValueError("source_url is required")
        self.source_ref = source_ref.strip()
        self.source_url = source_url.strip()

    @staticmethod
    def _constituent(raw_token: str) -> CompleteSnapshotConstituent:
        lineage_token = raw_token.strip().upper()
        if not lineage_token:
            raise ValueError("empty constituent token in complete snapshot")
        match = _LINEAGE_SUFFIX.fullmatch(lineage_token)
        return CompleteSnapshotConstituent(
            lineage_token=lineage_token,
            display_symbol=normalize_display_symbol(lineage_token),
            lineage_end_yyyymm=(match.group("end_yyyymm") if match is not None else None),
        )

    def load_latest_on_or_before(
        self,
        path: Path,
        *,
        target_date: date,
        observed_at: datetime,
        universe_code: str = "sp500",
    ) -> CompleteUniverseSnapshotAnchor:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        source_bytes = path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        rows: list[tuple[date, str]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {"date", "tickers"}.issubset(reader.fieldnames):
                raise ValueError("historical snapshot CSV must contain date,tickers columns")
            for row in reader:
                raw_date = (row.get("date") or "").strip()
                raw_tickers = (row.get("tickers") or "").strip()
                if not raw_date or not raw_tickers:
                    continue
                effective_at = date.fromisoformat(raw_date)
                if effective_at <= target_date:
                    rows.append((effective_at, raw_tickers))
        if not rows:
            raise ValueError(f"no complete snapshot exists on or before {target_date.isoformat()}")

        effective_at, raw_tickers = max(rows, key=lambda item: item[0])
        constituents = tuple(
            sorted(
                (self._constituent(token) for token in raw_tickers.split(",")),
                key=lambda item: item.lineage_token,
            )
        )
        lineage_tokens = [item.lineage_token for item in constituents]
        if len(lineage_tokens) != len(set(lineage_tokens)):
            raise ValueError("complete snapshot contains duplicate lineage tokens")
        if not 490 <= len(constituents) <= 510:
            raise ValueError(
                "complete S&P 500 snapshot has implausible constituent count: "
                f"{len(constituents)}"
            )

        return CompleteUniverseSnapshotAnchor(
            universe_code=universe_code.strip().lower(),
            effective_at=effective_at,
            constituents=constituents,
            source=self.source_name,
            source_url=self.source_url,
            source_ref=self.source_ref,
            source_observed_at=observed_at,
            source_hash=source_hash,
        )
