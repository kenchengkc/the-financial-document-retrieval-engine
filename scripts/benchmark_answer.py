"""End-to-end answer-quality benchmark for the mock extractive generator.

Runs the full answer workflow (preprocess -> multi-query retrieve -> rerank ->
gate -> neighbor-expand -> generate -> verify) over the labeled query set with
neighbor expansion off vs on, and reports generation-step metrics:

- answer_rate          : fraction of queries that produce an answer (don't abstain)
- answer_on_target     : answer cites a chunk from the expected issuer + section
- citation_grounding   : fraction of answers whose every citation is in the evidence
- abstention_rate      : fraction that abstain
- mean_confidence

Notes on interpretation: the mock generator is *extractive* (one claim from the
top hit), so it is grounded by construction and neighbor context does not change
the answer — neighbor expansion's value would only surface with a synthesizing
(LLM) generator. A stricter "answer cites the exact labeled chunk" reads ~0
because the top hit is usually a different, also-relevant chunk in the same
section; answer_on_target is the meaningful relevance proxy.

    PYTHONPATH=packages/fdre:. VOYAGE_API_KEY=... python3.11 -m scripts.benchmark_answer
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from fdre.citations.verifier import CitationVerifier
from fdre.evals.datasets import EvalQuestion
from fdre.graph.nodes import GeneratedAnswer, MockAnswerGenerator, WorkflowContext
from fdre.graph.workflow import run_answer_workflow
from fdre.retrieval.query import RetrievalCandidate


def _run(questions: list[EvalQuestion], window: int) -> dict[str, float]:
    settings = get_settings().model_copy(
        update={"reranker_provider": "voyage", "neighbor_expansion_window": window}
    )
    answered = on_target = grounded = abstained = 0
    confidences: list[float] = []
    with Session(create_db_engine()) as session:
        context = WorkflowContext(
            session=session,
            settings=settings,
            generator=MockAnswerGenerator(),
            verifier=CitationVerifier(),
        )
        for question in questions:
            state = run_answer_workflow(context, question.question)
            if state.get("should_abstain") or state.get("answer") is None:
                abstained += int(bool(state.get("should_abstain")))
                continue
            answer = GeneratedAnswer.model_validate(state["answer"])
            if not answer.claims:
                continue
            answered += 1
            confidences.append(answer.confidence)
            evidence = {
                candidate.chunk_id: candidate
                for candidate in (
                    RetrievalCandidate.model_validate(payload)
                    for payload in state.get("evidence", [])
                )
            }
            cited = {cid for claim in answer.claims for cid in claim.citation_chunk_ids}
            if cited and all(cid in evidence for cid in cited):
                grounded += 1
            if any(
                cid in evidence
                and evidence[cid].metadata.get("ticker") in question.expected_tickers
                and (
                    not question.expected_sections
                    or evidence[cid].metadata.get("section") in question.expected_sections
                )
                for cid in cited
            ):
                on_target += 1
    total = len(questions)
    return {
        "answer_rate": answered / total,
        "answer_on_target": on_target / total,
        "citation_grounding": grounded / max(answered, 1),
        "abstention_rate": abstained / total,
        "mean_confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/evals/retrieval_benchmark.jsonl")
    args = parser.parse_args()
    questions = [
        EvalQuestion.model_validate_json(line)
        for line in Path(args.dataset).read_text().splitlines()
        if line.strip()
    ]
    off = _run(questions, window=0)
    on = _run(questions, window=1)
    print(f"\n{len(questions)} labeled queries | end-to-end answer quality\n")
    print(f"{'metric':<22} {'neighbors off':>14} {'neighbors on':>14}")
    print("-" * 52)
    for key in off:
        print(f"{key:<22} {off[key]:>14.3f} {on[key]:>14.3f}")


if __name__ == "__main__":
    main()
