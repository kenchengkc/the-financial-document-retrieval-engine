from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvalQuestion(BaseModel):
    question: str
    expected_tickers: list[str] = Field(default_factory=list)
    expected_sections: list[str] = Field(default_factory=list)
    relevant_chunk_ids: list[int] = Field(default_factory=list)
    answer_type: str = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_jsonl_dataset(path: str | Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            questions.append(EvalQuestion.model_validate_json(stripped))
        except ValueError as error:
            raise ValueError(f"Invalid eval record on line {line_number}") from error
    return questions


def write_jsonl_dataset(path: str | Path, questions: list[EvalQuestion]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            json.dumps(question.model_dump(mode="json"), sort_keys=True)
            for question in questions
        )
        + "\n"
    )
