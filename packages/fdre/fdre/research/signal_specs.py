from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

SignalOutcome = Literal["abnormal_return", "realized_volatility"]


@dataclass(frozen=True, slots=True)
class SignalSpec:
    key: str
    label: str
    family: str
    source: str
    formula: str
    thesis: str
    default_outcome: SignalOutcome
    default_windows: tuple[str, ...]
    legacy: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


SIGNAL_SPECS: dict[str, SignalSpec] = {
    "disclosure_similarity": SignalSpec(
        key="disclosure_similarity",
        label="Disclosure similarity",
        family="Language",
        source="Comparable filing passage fingerprints",
        formula="Jaccard overlap versus the prior comparable filing",
        thesis="Persistent disclosures may identify information the market processes slowly.",
        default_outcome="abnormal_return",
        default_windows=("0:1", "1:5", "1:21", "1:63"),
    ),
    "risk_factor_churn": SignalSpec(
        key="risk_factor_churn",
        label="Risk-factor churn",
        family="Language",
        source="Item 1A additions and removals",
        formula="(added passages + removed passages) / combined passage count",
        thesis="Large two-sided rewrites indicate changing uncertainty and should predict risk.",
        default_outcome="realized_volatility",
        default_windows=("1:21", "1:63"),
    ),
    "filing_delay_surprise": SignalSpec(
        key="filing_delay_surprise",
        label="Filing-delay surprise",
        family="Timing",
        source="Acceptance time and issuer filing history",
        formula="Current delay minus the expanding issuer-form median delay",
        thesis="An issuer-specific reporting slowdown is more informative than raw lateness.",
        default_outcome="realized_volatility",
        default_windows=("1:21", "1:63"),
    ),
    "earnings_quality": SignalSpec(
        key="earnings_quality",
        label="Cash-conversion quality",
        family="Fundamental",
        source="Net income, operating cash flow, and assets",
        formula="(operating cash flow - net income) / average assets",
        thesis="Cash-backed earnings should be more persistent than accrual-heavy earnings.",
        default_outcome="abnormal_return",
        default_windows=("1:63", "1:126", "1:252"),
    ),
    "operating_profitability": SignalSpec(
        key="operating_profitability",
        label="Operating profitability",
        family="Fundamental",
        source="Operating income and assets",
        formula="Operating income / average assets",
        thesis="Efficient operating profitability should support medium-horizon returns.",
        default_outcome="abnormal_return",
        default_windows=("1:63", "1:126", "1:252"),
    ),
    "operating_margin_momentum": SignalSpec(
        key="operating_margin_momentum",
        label="Margin momentum",
        family="Fundamental",
        source="Current and prior annual operating income and revenue",
        formula="Current operating margin - prior operating margin",
        thesis=(
            "Improving unit economics can identify fundamental acceleration before "
            "consensus catches up."
        ),
        default_outcome="abnormal_return",
        default_windows=("1:21", "1:63", "1:126"),
    ),
    "asset_growth": SignalSpec(
        key="asset_growth",
        label="Disciplined investment",
        family="Fundamental",
        source="Comparative annual assets",
        formula="Negative year-over-year asset growth",
        thesis="Aggressive balance-sheet expansion may reduce future returns.",
        default_outcome="abnormal_return",
        default_windows=("1:63", "1:126", "1:252"),
    ),
    "net_share_issuance": SignalSpec(
        key="net_share_issuance",
        label="Net share issuance",
        family="Capital allocation",
        source="Reported common shares outstanding with diluted-share fallback",
        formula="Negative year-over-year share-count growth",
        thesis="Net repurchasers may outperform firms funding growth through dilution.",
        default_outcome="abnormal_return",
        default_windows=("1:63", "1:126", "1:252"),
    ),
    "risk_factor_expansion": SignalSpec(
        key="risk_factor_expansion",
        label="Net risk expansion",
        family="Language",
        source="Item 1A additions minus removals",
        formula="Added passages - removed passages",
        thesis="A larger net risk section may indicate changing operating uncertainty.",
        default_outcome="realized_volatility",
        default_windows=("1:21", "1:63"),
        legacy=True,
    ),
    "filing_lateness": SignalSpec(
        key="filing_lateness",
        label="Raw filing lateness",
        family="Timing",
        source="Acceptance time minus period end",
        formula="Calendar days from period end to acceptance",
        thesis="Slow reporting may indicate operating or control complexity.",
        default_outcome="realized_volatility",
        default_windows=("1:21", "1:63"),
        legacy=True,
    ),
    "composite": SignalSpec(
        key="composite",
        label="Filing-behavior composite",
        family="Composite",
        source="Sector-period standardized filing features",
        formula="Mean of sign-aligned component z-scores",
        thesis="Diversifying weak, orthogonal features may improve breadth-adjusted information.",
        default_outcome="abnormal_return",
        default_windows=("0:1", "1:21", "1:63"),
        legacy=True,
    ),
}


def get_signal_spec(signal_name: str) -> SignalSpec:
    try:
        return SIGNAL_SPECS[signal_name]
    except KeyError as error:
        raise ValueError(f"Unknown signal {signal_name!r}") from error
