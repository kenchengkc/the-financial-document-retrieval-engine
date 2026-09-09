import importlib


MODULES = (
    "anchor",
    "boundary",
    "evidence",
    "identity",
    "identity_adjudication",
    "identity_adjudication_apply",
    "identity_adjudication_manifest",
    "identity_strict_coverage",
    "identity_topology",
    "lineage",
    "materialization",
    "membership_adjudication",
    "membership_adjudication_apply",
    "membership_adjudication_manifest",
    "membership_continuity",
    "membership_continuity_apply",
    "pipeline",
    "residual_sec_evidence",
    "sec_identity",
    "security_type",
    "security_type_apply",
    "sources",
    "state_support",
    "strict_coverage",
)


def test_historical_universe_root_is_a_package_with_stable_public_import() -> None:
    module = importlib.import_module("fdre.research.historical_universe")

    assert hasattr(module, "__path__")
    assert module.SecurityIdentityRecord.__module__ == "fdre.research.historical_universe"
    assert module.UniverseMembershipRecord.__module__ == "fdre.research.historical_universe"


def test_flat_historical_universe_modules_reexport_canonical_package_modules() -> None:
    for name in MODULES:
        canonical = importlib.import_module(f"fdre.research.historical_universe.{name}")
        legacy = importlib.import_module(f"fdre.research.historical_universe_{name}")
        public_names = [item for item in vars(canonical) if not item.startswith("_")]

        missing = [item for item in public_names if not hasattr(legacy, item)]
        assert not missing, f"{name} compatibility import omitted: {missing}"
        for item in public_names:
            assert getattr(legacy, item) is getattr(canonical, item)
