"""Compatibility imports for :mod:`fdre.research.oos.implementation`."""

from fdre.research.oos import implementation as _impl
from fdre.research.oos.implementation import (
    ImplementationStatus,
    OOSCostScenarioResult,
    OOSImplementationConfig,
    OOSImplementationRebalance,
    OOSImplementationReport,
    OOSImplementationWindowResult,
    RebalanceFrequency,
    evaluate_oos_implementation,
    persist_oos_implementation,
    write_oos_implementation_report,
)

__all__ = [
    "ImplementationStatus",
    "OOSCostScenarioResult",
    "OOSImplementationConfig",
    "OOSImplementationRebalance",
    "OOSImplementationReport",
    "OOSImplementationWindowResult",
    "RebalanceFrequency",
    "evaluate_oos_implementation",
    "persist_oos_implementation",
    "write_oos_implementation_report",
]


def __getattr__(name: str) -> object:
    return getattr(_impl, name)
