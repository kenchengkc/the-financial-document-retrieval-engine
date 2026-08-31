from datetime import UTC, date, datetime

from fdre.research.historical_component_history import HistoricalComponentRecord
from fdre.research.historical_universe_boundary import BoundaryEvidenceIndex
from fdre.research.historical_universe_evidence import (
    MembershipEvidence,
    canonical_source_record_hash,
)
from fdre.research.historical_universe_lineage import TickerMembershipLineage

OBSERVED_AT = datetime(2026, 8, 31, tzinfo=UTC)


def _record(
    *,
    created_at: date = date(2010, 1, 1),
    approximate: bool = False,
) -> HistoricalComponentRecord:
    return HistoricalComponentRecord(
        symbol="ABC",
        cik="0000000001",
        name="Alpha Corp",
        sector="industrials",
        effective_from=date(2010, 1, 1),
        effective_to=date(2015, 1, 1),
        created_at=created_at,
        added_approximate=approximate,
        removed_approximate=approximate,
        source_ref="lawcal-ref",
        source_hash="a" * 64,
    )


def _evidence(event_type: str, when: date, source: str) -> MembershipEvidence:
    return MembershipEvidence(
        universe_code="sp500",
        event_type=event_type,  # type: ignore[arg-type]
        effective_at=when,
        raw_symbol="ABC",
        raw_name="Alpha Corp",
        source=source,
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(
            {"event_type": event_type, "when": when.isoformat(), "source": source}
        ),
    )


def _lineage() -> TickerMembershipLineage:
    return TickerMembershipLineage(
        symbol="ABC",
        effective_from=date(2010, 1, 1),
        effective_to=date(2015, 1, 1),
        source="fja05680/sp500-ticker-start-end",
        source_ref="fja-ref",
        source_hash="b" * 64,
    )


def test_exact_lawcal_boundaries_need_one_external_exact_match() -> None:
    result = BoundaryEvidenceIndex(evidence=(), lineages=(_lineage(),)).adjudicate(
        _record()
    )

    assert result.membership_boundaries_verified is True
    assert result.point_in_time_symbol_valid is True
    assert result.status == "verified"


def test_approximate_lawcal_boundaries_need_two_external_sources() -> None:
    start = date(2010, 1, 1)
    end = date(2015, 1, 1)
    one_source = BoundaryEvidenceIndex(evidence=(), lineages=(_lineage(),)).adjudicate(
        _record(approximate=True)
    )
    two_sources = BoundaryEvidenceIndex(
        evidence=(
            _evidence("addition", start, "source-two"),
            _evidence("removal", end, "source-two"),
        ),
        lineages=(_lineage(),),
    ).adjudicate(_record(approximate=True))

    assert one_source.status == "provisional_boundary"
    assert two_sources.status == "verified"


def test_later_symbol_creation_remains_provisional_after_date_corroboration() -> None:
    result = BoundaryEvidenceIndex(evidence=(), lineages=(_lineage(),)).adjudicate(
        _record(created_at=date(2012, 3, 4))
    )

    assert result.membership_boundaries_verified is True
    assert result.point_in_time_symbol_valid is False
    assert result.status == "provisional_identity"
    assert result.reasons == ("symbol_created_after_reported_membership_start",)
