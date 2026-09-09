from __future__ import annotations

import subprocess
import sys


def test_research_package_root_is_a_lightweight_namespace() -> None:
    script = """
import sys

import fdre.research as research

unexpected_modules = sorted(
    name
    for name in (
        "fdre.research.event_study",
        "fdre.research.experiment_registry",
        "fdre.research.filing_diffs",
        "fdre.research.financial_facts",
        "fdre.research.oos.diagnostics",
        "fdre.research.oos.implementation",
        "fdre.research.oos.promotion",
        "fdre.research.oos.selection",
        "fdre.research.panel",
        "fdre.research.screen",
        "fdre.research.thematic",
        "fdre.research.verification",
        "fdre.research.walk_forward",
    )
    if name in sys.modules
)
assert not unexpected_modules, unexpected_modules
assert not hasattr(research, "ResearchPanel")
assert not hasattr(research, "run_event_study")
"""
    subprocess.run([sys.executable, "-c", script], check=True)
