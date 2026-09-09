"""Compatibility imports for :mod:`fdre.research.oos.selection`."""

from fdre.research.oos import selection as _impl
from fdre.research.oos.selection import (
    OOSHypothesisDecision,
    OOSSelectionConfig,
    OOSSelectionStatus,
    OOSSelectionSuiteReport,
    _one_sided_sign_flip_p_value,
    evaluate_oos_selection_suite,
    persist_oos_selection_suite,
    write_oos_selection_report,
)

__all__ = [
    "OOSHypothesisDecision",
    "OOSSelectionConfig",
    "OOSSelectionStatus",
    "OOSSelectionSuiteReport",
    "_one_sided_sign_flip_p_value",
    "evaluate_oos_selection_suite",
    "persist_oos_selection_suite",
    "write_oos_selection_report",
]


def __getattr__(name: str) -> object:
    return getattr(_impl, name)
