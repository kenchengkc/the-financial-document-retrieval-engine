from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from fdre.evals.cross_sectional import (
    CrossSectionalMetrics,
    CrossSectionalOutcome,
    evaluate_cross_sectional_outcomes,
)
from fdre.evals.datasets import EvalQuestion
from fdre.research.screen import ResearchScreenPlan, ResearchScreenResponse

ScreenExecutor = Callable[[ResearchScreenPlan], ResearchScreenResponse]


def build_cross_sectional_screen_plan(question: EvalQuestion) -> ResearchScreenPlan:
    """Build the exact typed screen plan encoded by one benchmark question."""
    if question.as_of is None:
        raise ValueError(f"{question.question_id}: missing as_of")
    raw_plan = question.metadata.get("screen_plan")
    if not isinstance(raw_plan, dict):
        raise ValueError(f"{question.question_id}: missing metadata.screen_plan")
    if "as_of" in raw_plan:
        raise ValueError(
            f"{question.question_id}: screen_plan.as_of must use the top-level as_of"
        )
    return ResearchScreenPlan.model_validate({**raw_plan, "as_of": question.as_of})


def run_cross_sectional_benchmark(
    questions: list[EvalQuestion],
    *,
    execute_screen: ScreenExecutor,
    ks: tuple[int, ...] = (1, 3, 5),
) -> CrossSectionalMetrics:
    """Execute each frozen screen once, then score the returned issuer ranking."""
    outcomes: list[CrossSectionalOutcome] = []
    for question in questions:
        plan = build_cross_sectional_screen_plan(question)
        started = perf_counter()
        response = execute_screen(plan)
        latency_ms = round((perf_counter() - started) * 1000)
        if response.plan != plan:
            raise ValueError(
                f"{question.question_id}: screen executor returned a different plan"
            )
        outcomes.append(
            CrossSectionalOutcome(
                question=question,
                response=response.model_copy(update={"latency_ms": latency_ms}),
            )
        )
    return evaluate_cross_sectional_outcomes(outcomes, ks=ks)
