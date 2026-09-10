import importlib

MODULES = (
    ("specs", "signal_specs"),
    ("study", "signal_study"),
    ("composite", "composite_study"),
    ("risk_churn_acceleration", "risk_churn_acceleration"),
)


def test_signals_package_is_lightweight() -> None:
    module = importlib.import_module("fdre.research.signals")

    assert hasattr(module, "__path__")
    assert not hasattr(module, "SignalStudyReport")


def test_legacy_signal_modules_reexport_canonical_public_surfaces() -> None:
    for canonical_name, legacy_name in MODULES:
        canonical = importlib.import_module(f"fdre.research.signals.{canonical_name}")
        legacy = importlib.import_module(f"fdre.research.{legacy_name}")
        public_names = [name for name in vars(canonical) if not name.startswith("_")]

        missing = [name for name in public_names if not hasattr(legacy, name)]
        assert not missing, f"{legacy_name} compatibility import omitted: {missing}"
        for name in public_names:
            assert getattr(legacy, name) is getattr(canonical, name)
