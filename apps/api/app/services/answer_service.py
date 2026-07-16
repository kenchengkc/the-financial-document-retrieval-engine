from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import AnswerRun, Citation
from fdre.citations.verifier import CitationVerifier, VerifiedCitation
from fdre.graph.nodes import GeneratedAnswer, MockAnswerGenerator, WorkflowContext
from fdre.graph.workflow import run_answer_workflow
from fdre.retrieval.query import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class AnswerServiceResult:
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


def answer_question(
    session: Session,
    settings: Settings,
    *,
    question: str,
) -> AnswerServiceResult:
    started = perf_counter()
    if settings.answer_generator != "mock":
        raise ValueError(
            "Only ANSWER_GENERATOR=mock is available in the no-cost MVP runtime."
        )
    state = run_answer_workflow(
        WorkflowContext(
            session=session,
            settings=settings,
            generator=MockAnswerGenerator(),
            verifier=CitationVerifier(),
        ),
        question,
    )
    answer = (
        GeneratedAnswer.model_validate(state["answer"])
        if state.get("answer") is not None
        else None
    )
    evidence = [
        RetrievalCandidate.model_validate(candidate)
        for candidate in state.get("evidence", [])
    ]
    citations = [
        VerifiedCitation.model_validate(citation)
        for citation in state.get("citations", [])
    ]
    retrieval_gate = dict(state.get("retrieval_gate", {}))
    confidence = _grounding_confidence(answer, citations, retrieval_gate)
    if confidence is not None:
        retrieval_gate["confidence"] = confidence
        retrieval_gate["confidence_components"] = {
            "top_rerank": _bounded_score(retrieval_gate.get("max_score")),
            "mean_citation_overlap": mean(citation.confidence for citation in citations),
            "weights": {"top_rerank": 0.6, "citation_overlap": 0.4},
        }
    latency_ms = round((perf_counter() - started) * 1000)
    trace = state.get("trace", [])
    answer_run = AnswerRun(
        question=question,
        rewritten_queries_json=state.get("rewritten_queries", []),
        route_json={"routes": state.get("route", [])},
        answer_text=answer.answer_text if answer else None,
        confidence=confidence,
        abstained=bool(state.get("should_abstain")),
        abstention_reason=state.get("abstention_reason"),
        latency_ms=latency_ms,
        trace_json={
            "steps": trace,
            "retrieval_gate": retrieval_gate,
            "errors": state.get("errors", []),
            "financial_facts": state.get("financial_facts", []),
        },
    )
    for verified in citations:
        answer_run.citations.append(
            Citation(
                chunk_id=verified.chunk_id,
                claim_text=verified.claim_text,
                citation_text=verified.citation_text,
                page_number=_optional_int(verified.metadata.get("page_number")),
                section=_optional_str(verified.metadata.get("section")),
                confidence=verified.confidence,
            )
        )
    session.add(answer_run)
    session.commit()
    session.refresh(answer_run)
    return AnswerServiceResult(
        answer_run_id=answer_run.id,
        question=question,
        rewritten_queries=state.get("rewritten_queries", []),
        route=state.get("route", []),
        answer=answer.answer_text if answer else None,
        confidence=confidence,
        abstained=bool(state.get("should_abstain")),
        abstention_reason=state.get("abstention_reason"),
        evidence=evidence,
        citations=citations,
        financial_facts=state.get("financial_facts", []),
        retrieval_gate=retrieval_gate,
        trace=trace,
        latency_ms=latency_ms,
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _grounding_confidence(
    answer: GeneratedAnswer | None,
    citations: list[VerifiedCitation],
    retrieval_gate: dict[str, Any],
) -> float | None:
    """Combine ranked relevance with post-generation citation support.

    The generator's selected passage score is not a retrieval confidence: it can
    be lower than the gate's top hit when a numerically substantive passage is
    selected for the answer. Keep retrieval relevance dominant and use verified
    citation overlap as the grounding check.
    """
    if answer is None or not retrieval_gate.get("passed") or not citations:
        return None
    retrieval_score = _bounded_score(retrieval_gate.get("max_score"))
    citation_score = mean(citation.confidence for citation in citations)
    return round(0.6 * retrieval_score + 0.4 * citation_score, 4)


def _bounded_score(value: object) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return min(1.0, max(0.0, float(value)))
