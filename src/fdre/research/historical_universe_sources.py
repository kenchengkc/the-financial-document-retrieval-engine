"""Additional public source adapters for Historical Universe membership evidence."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from fdre.research.historical_universe_evidence import (
    MembershipEventType,
    MembershipEvidence,
    canonical_source_record_hash,
)


class WikipediaHistoricalComponentsAdapter:
    """Parse Wikipedia's S&P 500 component-change table from a local HTML copy.

    The maintained table lives on ``List of S&P 500 companies``. The source revision is
    attributed in every record when callers provide a pinned ``oldid`` URL. FDRE does not
    download or bundle Wikipedia content. Rows that are explicitly ticker/name changes are
    skipped because they describe identity mutation rather than index entry or exit.
    """

    source_name = "wikipedia-sp500-historical-components"
    default_source_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    def __init__(
        self,
        *,
        universe_code: str = "sp500",
        source_url: str | None = None,
    ) -> None:
        self.universe_code = universe_code
        self.source_url = source_url or self.default_source_url

    @staticmethod
    def _parse_date(value: str, row_number: int) -> date:
        try:
            return datetime.strptime(value.strip(), "%B %d, %Y").date()
        except ValueError as exc:
            raise ValueError(
                f"invalid Wikipedia effective date on row {row_number}: {value!r}"
            ) from exc

    @staticmethod
    def _table(soup: BeautifulSoup) -> Tag:
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            header = " ".join(table.stripped_strings)
            if all(token in header for token in ("Effective Date", "Added", "Removed", "Reason")):
                return table
        raise ValueError("could not find Wikipedia S&P 500 component-change table")

    @staticmethod
    def _is_identity_only(reason: str) -> bool:
        normalized = reason.lower()
        markers = (
            "changed its ticker symbol",
            "changed its ticker",
            "ticker symbol changed",
            "changed its name to",
            "changed its name from",
        )
        return any(marker in normalized for marker in markers)

    def load(
        self,
        path: Path,
        *,
        observed_at: datetime,
    ) -> tuple[MembershipEvidence, ...]:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        table = self._table(soup)
        evidence: list[MembershipEvidence] = []

        for row_number, row in enumerate(table.find_all("tr"), start=1):
            if not isinstance(row, Tag):
                continue
            cells = row.find_all("td", recursive=False)
            if len(cells) < 6:
                continue
            values = [cell.get_text(" ", strip=True) for cell in cells]
            effective_raw, add_symbol, add_name, remove_symbol, remove_name, reason = values[:6]
            if not effective_raw:
                continue
            if self._is_identity_only(reason):
                continue
            effective_at = self._parse_date(effective_raw, row_number)
            row_payload = {
                "effective_date": effective_raw,
                "addition_ticker": add_symbol,
                "addition_security": add_name,
                "removal_ticker": remove_symbol,
                "removal_security": remove_name,
                "reason": reason,
            }
            record_hash = canonical_source_record_hash(row_payload)
            row_id = hashlib.sha256(
                f"{effective_raw}|{add_symbol}|{remove_symbol}|{reason}".encode()
            ).hexdigest()

            pairs: tuple[tuple[MembershipEventType, str, str], ...] = (
                ("addition", add_symbol, add_name),
                ("removal", remove_symbol, remove_name),
            )
            for event_type, raw_symbol, raw_name in pairs:
                if not raw_symbol.strip():
                    continue
                evidence.append(
                    MembershipEvidence(
                        universe_code=self.universe_code,
                        event_type=event_type,
                        effective_at=effective_at,
                        effective_session="unspecified",
                        raw_symbol=raw_symbol.strip(),
                        raw_name=raw_name.strip() or None,
                        source=self.source_name,
                        source_url=self.source_url,
                        source_observed_at=observed_at,
                        source_record_id=row_id,
                        source_record_hash=record_hash,
                        metadata=(("reason", reason),) if reason else (),
                    )
                )

        evidence.sort(
            key=lambda item: (
                item.effective_at,
                item.event_type,
                item.raw_symbol,
                item.evidence_id,
            )
        )
        return tuple(evidence)
