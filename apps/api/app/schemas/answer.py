from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fdre.citations.verifier import VerifiedCitation
from fdre.retrieval.query import RetrievalCandidate


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1)


class AnswerResponse(BaseModel):
    answer_run_id: int
    question: str
    rewritten_queries: list[str]
    route: list[str]
    answer: str | None
    confidence: float | None
    abstained: bool
    abstention_reason: str | None
    evidence: list[RetrievalCandidate]
    citations: list[VerifiedCitation]
    financial_facts: list[dict[str, Any]]
    retrieval_gate: dict[str, Any]
    trace: list[dict[str, Any]]
    latency_ms: int
