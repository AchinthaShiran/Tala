"""Evaluation runners.

* retrieval mode: no LLM needed; measures whether the right tool is among the candidates.
* agent mode: runs the real graph with a live model but a *simulated* command runner and
  automatic denial of approvals, so nothing on the machine is ever changed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from assistant.config import RetrievalSettings
from assistant.domain import (
    ApprovalRequestedEvent,
    ExecutionResult,
    ToolProposedEvent,
    current_platform,
)
from assistant.evaluation.cases import EvalCase
from assistant.packs import ToolRegistry
from assistant.retrieval import Confidence, ToolIndex
from assistant.service import Assistant


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: EvalCase
    passed: bool
    detail: str
    skipped: bool = False
    seconds: float = 0.0


@dataclass
class EvalReport:
    mode: str
    results: list[CaseResult] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed and not r.skipped]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def evaluate_retrieval(
    registry_tools: Sequence[Any],
    cases: Sequence[EvalCase],
    settings: RetrievalSettings,
    index: ToolIndex | None = None,
) -> EvalReport:
    """Score tool retrieval over every tool defined for this OS (ignores what is installed)."""
    owns_index = index is None
    if index is None:
        index = ToolIndex(":memory:", settings, embeddings=None)
        index.sync(registry_tools)
    report = EvalReport(mode="retrieval")
    available = {getattr(t, "name", None) for t in registry_tools}
    # Cases whose tools exist only on another OS cannot be scored here (as in agent evaluation).
    runnable = [c for c in cases if not c.expects_tool or available & set(c.expect)]
    tool_cases = [c for c in runnable if c.expects_tool]
    chat_cases = [c for c in runnable if not c.expects_tool]
    recalled = top1 = false_strong = 0
    for case in cases:
        if case not in runnable:
            report.results.append(
                CaseResult(case, False, "no expected tool is defined for this OS", skipped=True)
            )
            continue
        result = index.search(case.query)
        if case.expects_tool:
            in_k = any(name in case.expect for name in result.names)
            first = bool(result.names) and result.names[0] in case.expect
            recalled += in_k
            top1 += first
            report.results.append(
                CaseResult(
                    case, in_k, f"top={result.names[:3]} confidence={result.confidence.value}"
                )
            )
        else:
            strong = result.confidence is Confidence.STRONG
            false_strong += strong
            report.results.append(
                CaseResult(
                    case, not strong, f"confidence={result.confidence.value} top={result.names[:2]}"
                )
            )
    report.metrics = {
        f"recall@{settings.top_k}": _ratio(recalled, len(tool_cases)),
        "top1": _ratio(top1, len(tool_cases)),
        "false_strong_rate": _ratio(false_strong, len(chat_cases)),
    }
    if owns_index:
        index.close()
    return report


class SimulatedRunner:
    """Pretends to run commands so agent evaluation never touches the machine."""

    def run(
        self, argv: Sequence[str], *, timeout: float, max_bytes: int, encoding: str = "utf-8"
    ) -> ExecutionResult:
        return ExecutionResult(tuple(argv), 0, "(simulated output)", "", 0.0)


def evaluate_agent(
    assistant: Assistant,
    available_tools: set[str],
    cases: Sequence[EvalCase],
    progress: Callable[[int, int, CaseResult], None] | None = None,
) -> EvalReport:
    """Run each case through the agent. Its command runner must be a ``SimulatedRunner``."""
    report = EvalReport(mode="agent")
    selected = correct_args = tool_total = chat_total = chat_ok = 0
    for number, case in enumerate(cases, start=1):
        if case.expects_tool and not set(case.expect) & available_tools:
            result = CaseResult(case, False, "no expected tool is available here", skipped=True)
        else:
            result = _run_case(assistant, case, f"eval-{number}")
            if case.expects_tool:
                tool_total += 1
                selected += result.passed
                correct_args += result.passed and "args ok" in result.detail
            else:
                chat_total += 1
                chat_ok += result.passed
        report.results.append(result)
        if progress:
            progress(number, len(cases), result)
    timed = [r.seconds for r in report.results if not r.skipped]
    report.metrics = {
        "tool_selection": _ratio(selected, tool_total),
        "argument_match": _ratio(correct_args, tool_total),
        "chat_no_tool": _ratio(chat_ok, chat_total),
        "avg_seconds": sum(timed) / len(timed) if timed else 0.0,
    }
    return report


def _run_case(assistant: Assistant, case: EvalCase, session: str) -> CaseResult:
    started = time.monotonic()
    proposed: list[ToolProposedEvent] = []
    events = assistant.send(session, case.query)
    while True:
        pending: ApprovalRequestedEvent | None = None
        for event in events:
            if isinstance(event, ToolProposedEvent):
                proposed.append(event)
            elif isinstance(event, ApprovalRequestedEvent):
                pending = event
        if pending is None:
            break
        events = assistant.resume(session, {r.call_id: False for r in pending.requests})
    assistant.reset(session)
    seconds = time.monotonic() - started

    if not case.expects_tool:
        ok = not proposed
        return CaseResult(
            case, ok, "no tool" if ok else f"proposed {proposed[0].tool}", seconds=seconds
        )
    if not proposed:
        return CaseResult(case, False, "no tool proposed", seconds=seconds)
    first = proposed[0]
    if first.tool not in case.expect:
        return CaseResult(case, False, f"proposed {first.tool}", seconds=seconds)
    wrong = {k: v for k, v in case.args.items() if str(first.arguments.get(k)) != str(v)}
    detail = "args ok" if not wrong else f"args differ: {wrong} vs {first.arguments}"
    return CaseResult(case, True, f"{first.tool}; {detail}", seconds=seconds)


def registry_for_retrieval_eval(tools: Sequence[Any]) -> ToolRegistry:
    """All tools defined for this OS, regardless of which executables are installed."""
    return ToolRegistry(tools, current_platform(), which=lambda exe: exe)
