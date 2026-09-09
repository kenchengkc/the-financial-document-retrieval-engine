import fdre.research.oos_diagnostics as legacy_diagnostics
import fdre.research.oos_implementation as legacy_implementation
import fdre.research.oos_promotion as legacy_promotion
import fdre.research.oos_selection as legacy_selection
from fdre.research.oos import diagnostics, implementation, promotion, selection


def test_legacy_oos_imports_resolve_to_package_implementations() -> None:
    assert legacy_diagnostics.OOSDiagnosticsConfig is diagnostics.OOSDiagnosticsConfig
    assert legacy_diagnostics.build_oos_diagnostics is diagnostics.build_oos_diagnostics

    assert legacy_selection.OOSSelectionConfig is selection.OOSSelectionConfig
    assert legacy_selection.evaluate_oos_selection_suite is selection.evaluate_oos_selection_suite
    assert (
        legacy_selection._one_sided_sign_flip_p_value
        is selection._one_sided_sign_flip_p_value
    )

    assert legacy_implementation.OOSImplementationConfig is implementation.OOSImplementationConfig
    assert (
        legacy_implementation.evaluate_oos_implementation
        is implementation.evaluate_oos_implementation
    )

    assert legacy_promotion.OOSPromotionConfig is promotion.OOSPromotionConfig
    assert legacy_promotion.evaluate_oos_promotion is promotion.evaluate_oos_promotion
