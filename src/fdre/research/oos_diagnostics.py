"""Compatibility imports for :mod:`fdre.research.oos.diagnostics`."""

from fdre.research.oos import diagnostics as _impl
from fdre.research.oos.diagnostics import (
    FoldDiagnosticsStatus,
    OOSDiagnosticsConfig,
    OOSDiagnosticsReport,
    OOSDiagnosticsStatus,
    OOSFoldWindowDiagnostic,
    OOSQuantileResult,
    OOSWindowDiagnostic,
    build_oos_diagnostics,
    persist_oos_diagnostics,
    write_oos_diagnostics_report,
)

__all__ = [
    "FoldDiagnosticsStatus",
    "OOSDiagnosticsConfig",
    "OOSDiagnosticsReport",
    "OOSDiagnosticsStatus",
    "OOSFoldWindowDiagnostic",
    "OOSQuantileResult",
    "OOSWindowDiagnostic",
    "build_oos_diagnostics",
    "persist_oos_diagnostics",
    "write_oos_diagnostics_report",
]


def __getattr__(name: str) -> object:
    return getattr(_impl, name)
