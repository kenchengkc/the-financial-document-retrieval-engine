"""Compatibility imports for :mod:`fdre.research.oos.promotion`."""

from fdre.research.oos import promotion as _impl
from fdre.research.oos.promotion import (
    OOSPromotionConfig,
    OOSPromotionDecision,
    OOSPromotionReport,
    OOSRobustnessSliceResult,
    OOSSignalDecayPoint,
    PromotionStatus,
    evaluate_oos_promotion,
    persist_oos_promotion,
    write_oos_promotion_report,
)

__all__ = [
    "OOSPromotionConfig",
    "OOSPromotionDecision",
    "OOSPromotionReport",
    "OOSRobustnessSliceResult",
    "OOSSignalDecayPoint",
    "PromotionStatus",
    "evaluate_oos_promotion",
    "persist_oos_promotion",
    "write_oos_promotion_report",
]


def __getattr__(name: str) -> object:
    return getattr(_impl, name)
