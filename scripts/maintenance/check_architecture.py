"""Fail when repository paths drift back into deprecated flat namespaces."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".ini", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
SCAN_ROOTS = (".github", "apps", "docs", "scripts", "src", "tests")
ROOT_TEXT_FILES = ("AGENTS.md", "README.md", "pyproject.toml")
FLAT_SCRIPT_PATH = re.compile(r"(?<![A-Za-z0-9_])scripts/([A-Za-z0-9_]+\.py)")
FLAT_SCRIPT_MODULE = re.compile(r"(?<![A-Za-z0-9_])scripts\.([A-Za-z0-9_]+)(?=[^A-Za-z0-9_.]|$)")
ALLOWED_SCRIPT_ROOT_FILES = {"__init__.py"}
ALLOWED_DOC_ROOT_MARKDOWN = {"README.md", "roadmap.md"}


def _text_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if relative.parts[:2] == ("docs", "archive"):
                continue
            files.append(path)
    for name in ROOT_TEXT_FILES:
        path = ROOT / name
        if path.exists():
            files.append(path)
    return tuple(sorted(set(files)))


def architecture_violations() -> tuple[str, ...]:
    violations: list[str] = []

    scripts_root = ROOT / "scripts"
    for path in sorted(scripts_root.glob("*.py")):
        if path.name not in ALLOWED_SCRIPT_ROOT_FILES:
            violations.append(f"flat script entry point: {path.relative_to(ROOT)}")

    docs_root = ROOT / "docs"
    for path in sorted(docs_root.glob("*.md")):
        if path.name not in ALLOWED_DOC_ROOT_MARKDOWN:
            violations.append(f"uncategorized active documentation: {path.relative_to(ROOT)}")

    for path in _text_files():
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if FLAT_SCRIPT_PATH.search(line) or FLAT_SCRIPT_MODULE.search(line):
                message = f"stale flat-script reference: {relative}:{line_number}: {line.strip()}"
                violations.append(message)

    return tuple(violations)


def main() -> int:
    violations = architecture_violations()
    if not violations:
        print("Repository architecture checks passed.")
        return 0

    print("Repository architecture violations:")
    for violation in violations:
        print(f"- {violation}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
