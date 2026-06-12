from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from fdre.citations.verifier import AnswerClaim, CitationVerifier
from fdre.graph.state import AgentState
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.research.financial_facts import FinancialFactQuery, query_financial_facts
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import load_company_references, preprocess_query
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.rerank import reranker_from_settings
from fdre.retrieval.sparse import SparseRetriever

PRIVATE_INFORMATION_PATTERN = re.compile(
    r"\b(?:private|non-public|inside information|insider|confidential)\b",
    re.I,
)
UNSUPPORTED_FORECAST_PATTERN = re.compile(
    r"\b(?:predict|forecast|guarantee|price target)\b"
    r".{0,40}\b(?:stock|share price|investment return|market return)\b"
    r"|\b(?:buy|sell|short)\s+(?:the\s+)?(?:stock|shares)\b",
    re.I,
)
REQUIRES_FINANCIAL_FACTS_PATTERN = re.compile(
    r"\b(?:compare|comparison|growth|versus|vs\.?|year-over-year|yoy)\b",
    re.I,
)


class GeneratedAnswer(BaseModel):
    answer_text: str
    claims: list[AnswerClaim] = Field(default_factory=list)
    confidence: float


class AnswerGenerator(Protocol):
    def generate(
        self,
        question: str,
        evidence: list[RetrievalCandidate],
    ) -> GeneratedAnswer: ...


class MockAnswerGenerator:
    """Produce deterministic extractive claims from retrieved evidence."""

    def generate(
        self,
        question: str,
        evidence: list[RetrievalCandidate],
    ) -> GeneratedAnswer:
        narrative = [
            candidate
            for candidate in evidence
            if candidate.metadata.get("element_type") not in {"section_header", "title"}
            and candidate.metadata.get("element_type") != "table"
            and len(candidate.text.split()) >= 5
        ]
        substantive = [
            candidate
            for candidate in evidence
            if candidate.metadata.get("element_type") not in {"section_header", "title"}
            and len(candidate.text.split()) >= 5
        ]
        selection_limit = 2 if REQUIRES_FINANCIAL_FACTS_PATTERN.search(question) else 1
        selected = (narrative or substantive or evidence)[:selection_limit]
        claims = [
            AnswerClaim(
                claim_text=_first_sentence(candidate.text),
                citation_chunk_ids=[candidate.chunk_id],
                citation_text=candidate.text,
            )
            for candidate in selected
        ]
        return GeneratedAnswer(
            answer_text=" ".join(claim.claim_text for claim in claims),
            claims=claims,
            confidence=sum(_candidate_score(candidate) for candidate in selected)
            / max(len(selected), 1),
        )


@dataclass(slots=True)
class WorkflowContext:
    session: Session
    settings: Settings
    generator: AnswerGenerator
    verifier: CitationVerifier

    @property
    def retriever(self) -> HybridRetriever:
        provider = embedding_provider_from_settings(self.settings)
        return HybridRetriever(DenseRetriever(provider), SparseRetriever())


def preprocess_query_node(context: WorkflowContext, state: AgentState) -> AgentState:
    result = preprocess_query(
        state["user_query"],
        companies=load_company_references(context.session),
    )
    return {
        "rewritten_queries": result.rewritten_queries,
        "filters": result.filters.model_dump(mode="json"),
        "route": list(result.routes),
        "trace": _trace(
            state,
            "preprocess_query",
            {"filters": result.filters.model_dump(mode="json")},
        ),
    }


def route_tools_node(context: WorkflowContext, state: AgentState) -> AgentState:
    del context
    routes = state.get("route", ["text"])
    return {
        "route": routes,
        "trace": _trace(state, "route_tools", {"routes": routes}),
    }


def retrieve_text_node(context: WorkflowContext, state: AgentState) -> AgentState:
    filters = SearchFilters.model_validate(state.get("filters", {}))
    candidates = context.retriever.search(
        context.session,
        state["rewritten_queries"][0],
        filters=filters,
        limit=max(context.settings.answer_top_k, 10),
    )
    return {
        "text_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "trace": _trace(state, "retrieve_text", {"count": len(candidates)}),
    }


def retrieve_tables_node(context: WorkflowContext, state: AgentState) -> AgentState:
    if "tables" not in state.get("route", []):
        return {
            "table_candidates": [],
            "trace": _trace(state, "retrieve_tables", {"count": 0, "skipped": True}),
        }
    filters = SearchFilters.model_validate(state.get("filters", {})).model_copy(
        update={"element_types": ["table"]}
    )
    candidates = context.retriever.search(
        context.session,
        state["rewritten_queries"][0],
        filters=filters,
        limit=max(context.settings.answer_top_k, 10),
    )
    return {
        "table_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "trace": _trace(state, "retrieve_tables", {"count": len(candidates)}),
    }


def retrieve_financial_facts_node(
    context: WorkflowContext,
    state: AgentState,
) -> AgentState:
    if "financial_facts" not in state.get("route", []):
        return {
            "financial_facts": [],
            "trace": _trace(
                state,
                "retrieve_financial_facts",
                {"count": 0, "skipped": True},
            ),
        }
    filters = SearchFilters.model_validate(state.get("filters", {}))
    result = query_financial_facts(
        context.session,
        FinancialFactQuery(
            tickers=filters.tickers,
            as_of=filters.as_of,
            limit=20,
        ),
    )
    serialized = [fact.model_dump(mode="json") for fact in result.facts]
    return {
        "financial_facts": serialized,
        "trace": _trace(state, "retrieve_financial_facts", {"count": len(serialized)}),
    }


def merge_candidates_node(context: WorkflowContext, state: AgentState) -> AgentState:
    del context
    merged: dict[int, RetrievalCandidate] = {}
    for payload in [
        *state.get("text_candidates", []),
        *state.get("table_candidates", []),
    ]:
        candidate = RetrievalCandidate.model_validate(payload)
        existing = merged.get(candidate.chunk_id)
        if existing is None or _candidate_score(candidate) > _candidate_score(existing):
            merged[candidate.chunk_id] = candidate
    candidates = sorted(
        merged.values(),
        key=lambda candidate: (-_candidate_score(candidate), candidate.chunk_id),
    )
    return {
        "retrieved_candidates": [
            candidate.model_dump(mode="json") for candidate in candidates
        ],
        "trace": _trace(state, "merge_candidates", {"count": len(candidates)}),
    }


def rerank_node(context: WorkflowContext, state: AgentState) -> AgentState:
    candidates = [
        RetrievalCandidate.model_validate(payload)
        for payload in state.get("retrieved_candidates", [])
    ]
    reranked = reranker_from_settings(context.settings).rerank(
        state["user_query"],
        candidates,
        top_n=context.settings.answer_top_k,
    )
    floor = context.settings.min_rerank_score
    if floor > 0:
        reranked = [
            candidate for candidate in reranked if (candidate.rerank_score or 0.0) >= floor
        ]
    return {
        "reranked_candidates": [
            candidate.model_dump(mode="json") for candidate in reranked
        ],
        "trace": _trace(state, "rerank", {"count": len(reranked)}),
    }


def evaluate_retrieval_gate_node(
    context: WorkflowContext,
    state: AgentState,
) -> AgentState:
    candidates = [
        RetrievalCandidate.model_validate(payload)
        for payload in state.get("reranked_candidates", [])
    ]
    maximum = max((_candidate_score(candidate) for candidate in candidates), default=0.0)
    reason: str | None = None
    if PRIVATE_INFORMATION_PATTERN.search(state["user_query"]):
        reason = "The question asks for unavailable or non-public information."
    elif UNSUPPORTED_FORECAST_PATTERN.search(state["user_query"]):
        reason = "FDRE does not forecast securities prices or provide trading recommendations."
    elif (
        "financial_facts" in state.get("route", [])
        and REQUIRES_FINANCIAL_FACTS_PATTERN.search(state["user_query"])
        and not state.get("financial_facts")
    ):
        reason = "Structured financial facts required by the question are unavailable."
    elif len(candidates) < context.settings.min_evidence_chunks:
        reason = "Insufficient retrieved evidence."
    elif maximum < context.settings.min_retrieval_score:
        reason = "Retrieved evidence is below the confidence threshold."
    return {
        "retrieval_gate": {
            "evidence_count": len(candidates),
            "max_score": maximum,
            "passed": reason is None,
        },
        "evidence": [candidate.model_dump(mode="json") for candidate in candidates],
        "should_abstain": reason is not None,
        "abstention_reason": reason,
        "trace": _trace(
            state,
            "evaluate_retrieval_gate",
            {"passed": reason is None, "reason": reason},
        ),
    }


def generate_answer_node(context: WorkflowContext, state: AgentState) -> AgentState:
    if state.get("should_abstain"):
        return {"trace": _trace(state, "generate_answer", {"skipped": True})}
    evidence = [
        RetrievalCandidate.model_validate(payload) for payload in state.get("evidence", [])
    ]
    answer = context.generator.generate(state["user_query"], evidence)
    return {
        "answer": answer.model_dump(mode="json"),
        "trace": _trace(state, "generate_answer", {"claim_count": len(answer.claims)}),
    }


def verify_citations_node(context: WorkflowContext, state: AgentState) -> AgentState:
    if state.get("should_abstain") or not state.get("answer"):
        return {"trace": _trace(state, "verify_citations", {"skipped": True})}
    answer = GeneratedAnswer.model_validate(state["answer"])
    evidence = [
        RetrievalCandidate.model_validate(payload) for payload in state.get("evidence", [])
    ]
    verification = context.verifier.verify(answer.claims, evidence)
    return {
        "citations": [
            citation.model_dump(mode="json") for citation in verification.citations
        ],
        "errors": [*state.get("errors", []), *verification.errors],
        "should_abstain": not verification.valid,
        "abstention_reason": (
            None if verification.valid else "Citation verification failed."
        ),
        "trace": _trace(
            state,
            "verify_citations",
            {"valid": verification.valid, "errors": verification.errors},
        ),
    }


def finalize_or_abstain_node(
    context: WorkflowContext,
    state: AgentState,
) -> AgentState:
    del context
    if state.get("should_abstain"):
        return {
            "answer": None,
            "citations": [],
            "trace": _trace(
                state,
                "finalize_or_abstain",
                {"abstained": True, "reason": state.get("abstention_reason")},
            ),
        }
    return {
        "trace": _trace(state, "finalize_or_abstain", {"abstained": False})
    }


def _candidate_score(candidate: RetrievalCandidate) -> float:
    if candidate.rerank_score is not None:
        return candidate.rerank_score
    return candidate.hybrid_score or 0.0


def _trace(
    state: AgentState,
    node: str,
    details: dict[str, Any],
) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "details": details}]


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.split()).lstrip("•- ").strip()
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0].strip()
    if not sentence:
        return ""
    return sentence if sentence[-1] in ".!?" else f"{sentence}."
