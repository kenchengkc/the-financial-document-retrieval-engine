from collections import Counter

from scripts.research.historical_universe.historical_universe_anchor_reconciliation import (
    _REJECTED_FJA_DUPLICATE,
    _REJECTED_LAWCAL_SYMBOL,
    _SEC_CONFIRMED_GAP_IDENTITIES,
    _SEC_CONFIRMED_SOURCE_GAPS,
    _TERMINAL_SYMBOL_ALIASES,
)


def test_pinned_anchor_adjudication_is_complete_and_non_overlapping() -> None:
    actual_aliases = Counter(actual for actual, _ in _TERMINAL_SYMBOL_ALIASES)
    terminal_aliases = Counter(terminal for _, terminal in _TERMINAL_SYMBOL_ALIASES)
    gaps = Counter(symbol for symbol, _ in _SEC_CONFIRMED_SOURCE_GAPS)

    assert len(_TERMINAL_SYMBOL_ALIASES) == 35
    assert len(actual_aliases) == 35
    assert len(terminal_aliases) == 35
    assert len(_SEC_CONFIRMED_SOURCE_GAPS) == 18
    assert len(_SEC_CONFIRMED_GAP_IDENTITIES) == 18
    assert {row[0] for row in _SEC_CONFIRMED_GAP_IDENTITIES} == set(gaps)
    assert len({row[2] for row in _SEC_CONFIRMED_GAP_IDENTITIES}) == 18
    assert len(gaps) == 18
    assert not (set(terminal_aliases) & set(gaps))
    assert _REJECTED_LAWCAL_SYMBOL not in actual_aliases
    assert _REJECTED_FJA_DUPLICATE not in terminal_aliases
