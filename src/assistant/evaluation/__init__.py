"""Golden-set evaluation of tool selection."""

from assistant.evaluation.cases import EvalCase, load_cases
from assistant.evaluation.runner import (
    CaseResult,
    EvalReport,
    SimulatedRunner,
    evaluate_agent,
    evaluate_retrieval,
    registry_for_retrieval_eval,
)

__all__ = [
    "CaseResult",
    "EvalCase",
    "EvalReport",
    "SimulatedRunner",
    "evaluate_agent",
    "evaluate_retrieval",
    "load_cases",
    "registry_for_retrieval_eval",
]
