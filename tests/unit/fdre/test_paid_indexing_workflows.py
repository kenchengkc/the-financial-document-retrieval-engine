from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = [("ingest.yml", "ingest"), ("sp500-ingest.yml", "ingest-batch")]
WORKFLOW_DIR = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    # GitHub uses YAML 1.2; BaseLoader keeps `on` from becoming a YAML 1.1 boolean.
    workflow = yaml.load((WORKFLOW_DIR / name).read_text(), Loader=yaml.BaseLoader)
    assert isinstance(workflow, dict)
    return workflow


def _environment(values: dict[str, str], context: dict[str, str]) -> dict[str, str]:
    def expression(match: re.Match[str]) -> str:
        for term in match[1].split("||"):
            term = term.strip()
            value = term[1:-1] if term.startswith("'") else context.get(term, "")
            if value:
                return value
        return ""

    return {
        key: re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, value)
        for key, value in values.items()
    }


@pytest.mark.parametrize(("workflow_name", "job_name"), WORKFLOWS)
@pytest.mark.parametrize("provider", ["voyage", "openai"])
@pytest.mark.parametrize("approval", [None, "false", "true"])
def test_paid_prerequisites_require_manual_approval(
    tmp_path: Path,
    workflow_name: str,
    job_name: str,
    provider: str,
    approval: str | None,
) -> None:
    workflow = _workflow(workflow_name)
    output = tmp_path / "output"
    context = {
        "secrets.DATABASE_URL": "fake-database",
        "secrets.SEC_USER_AGENT": "unit-test",
        "secrets.VOYAGE_API_KEY": "fake-voyage-key",
        "secrets.OPENAI_API_KEY": "fake-openai-key",
        "vars.EMBEDDING_PROVIDER": provider,
        # A repository variable must never authorize scheduled paid calls.
        "vars.PAID_EMBEDDING_INDEXING_ENABLED": "true",
    }
    if approval is not None:
        context["github.event.inputs.allow_paid_indexing"] = approval
    prerequisites = workflow["jobs"]["prerequisites"]
    env = _environment(prerequisites["env"], context)
    result = subprocess.run(
        ["bash", "-e", "-c", prerequisites["steps"][0]["run"]],
        env={**os.environ, **env, "GITHUB_OUTPUT": str(output)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_text().strip() == f"enabled={'true' if approval == 'true' else 'false'}"
    if approval != "true":
        assert "paid" in result.stdout.lower()
    job_env = _environment(workflow["jobs"][job_name]["env"], context)
    assert job_env.get("PAID_EMBEDDING_INDEXING_ENABLED") == (approval or "false")


@pytest.mark.parametrize(
    ("workflow_name", "provider"),
    [
        ("ingest.yml", "local_hash"),
        ("sp500-ingest.yml", "local_hash"),
        ("sp500-ingest.yml", "voyage"),
        ("sp500-ingest.yml", "openai"),
    ],
)
def test_free_and_research_archive_ingestion_remain_available(
    tmp_path: Path, workflow_name: str, provider: str
) -> None:
    prerequisites = _workflow(workflow_name)["jobs"]["prerequisites"]
    context = {
        "secrets.DATABASE_URL": "fake-database",
        "secrets.SEC_USER_AGENT": "unit-test",
        "vars.EMBEDDING_PROVIDER": provider,
    }
    if provider != "local_hash":
        context["github.event.inputs.archive_spec"] = "2010-01-01:2025-12-31:true"
    output = tmp_path / "output"
    subprocess.run(
        ["bash", "-e", "-c", prerequisites["steps"][0]["run"]],
        env={
            **os.environ,
            **_environment(prerequisites["env"], context),
            "GITHUB_OUTPUT": str(output),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_text().strip() == "enabled=true"


@pytest.mark.parametrize(("workflow_name", "job_name"), WORKFLOWS)
def test_paid_manual_input_defaults_off_and_price_reaches_ingest_job(
    workflow_name: str, job_name: str
) -> None:
    workflow = _workflow(workflow_name)
    approval_input = workflow["on"]["workflow_dispatch"]["inputs"].get("allow_paid_indexing")
    assert approval_input is not None
    assert approval_input["type"] == "boolean"
    assert approval_input["default"] == "false"
    env = workflow["jobs"][job_name]["env"]
    assert _environment(env, {}).get("EMBEDDING_COST_PER_MILLION_TOKENS") == "0"
    priced_env = _environment(env, {"vars.EMBEDDING_COST_PER_MILLION_TOKENS": "0.12"})
    assert priced_env.get("EMBEDDING_COST_PER_MILLION_TOKENS") == "0.12"


def test_chained_batch_does_not_inherit_paid_approval(tmp_path: Path) -> None:
    workflow = _workflow("sp500-ingest.yml")
    step = next(
        step
        for step in workflow["jobs"]["ingest-batch"]["steps"]
        if step["name"] == "Queue next S&P 500 batch"
    )
    binary = tmp_path / "gh"
    arguments = tmp_path / "arguments"
    binary.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$ARGUMENTS"\n')
    binary.chmod(0o755)
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "ARGUMENTS": str(arguments),
            "OFFSET": "0",
            "LIMIT": "10",
            "RANGE_END": "20",
            "LANE": "0",
            "FILING_LIMIT": "1",
            "ANNUAL_LIMIT": "",
            "QUARTERLY_LIMIT": "",
            "FORCE_PARSE": "false",
            "INDEX_ONLY": "false",
            "ARCHIVE_SPEC": "",
            "LANE_SPEC": "0:1:20",
            "PAID_EMBEDDING_INDEXING_ENABLED": "true",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert arguments.exists()
    assert not any("allow_paid_indexing" in arg for arg in arguments.read_text().splitlines())
