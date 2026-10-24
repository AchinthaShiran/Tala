from __future__ import annotations

from assistant.config import RetrievalSettings, builtin_packs_dir
from assistant.domain import current_platform
from assistant.evaluation import (
    SimulatedRunner,
    evaluate_agent,
    evaluate_retrieval,
    load_cases,
)
from assistant.evaluation.cases import EvalCase
from assistant.packs import PackRoot, load_packs
from tests.support import ai, tool_call

TOOLS = [
    t
    for t in load_packs([PackRoot(builtin_packs_dir(), "builtin")]).tools.values()
    if t.supports(current_platform())
]


def test_golden_cases_load_and_reference_real_tools():
    cases = load_cases()
    names = {t.name for t in load_packs([PackRoot(builtin_packs_dir(), "b")]).tools.values()}
    assert len(cases) >= 50
    for case in cases:
        assert set(case.expect) <= names, case
    assert any(not c.expects_tool for c in cases) and any(c.expects_tool for c in cases)


def test_retrieval_quality_gate_keyword_mode():
    """Regression guard for tool selection quality (BM25-only is the worst case)."""
    report = evaluate_retrieval(TOOLS, load_cases(), RetrievalSettings())
    assert report.metrics[f"recall@{RetrievalSettings().top_k}"] >= 0.9, [
        str(r.case.query) for r in report.failures
    ]
    assert report.metrics["top1"] >= 0.8
    assert report.metrics["false_strong_rate"] <= 0.2


def test_agent_eval_scores_tool_choice_args_and_chat(make_harness):
    h = make_harness(
        {
            "executor": [
                ai("", tool_call("ping_host", {"host": "google.com"})),
                # case 1: correct
                ai("", tool_call("disk_free")),
                # case 2: wrong tool
            ],
            "chat": ["hi!"],  # case 3 is conversation: executor is never used
            "summarizer": ["done", "done"],
        }
    )
    cases = [
        EvalCase(query="ping google.com", expect="ping_host", args={"host": "google.com"}),
        EvalCase(query="check disk space", expect="memory_usage"),
        EvalCase(query="hello there", expect="none"),
    ]
    report = evaluate_agent(h.assistant, set(h.runtime.registry.available), cases)
    assert [r.passed for r in report.results] == [True, False, True]
    assert report.metrics["tool_selection"] == 0.5
    assert report.metrics["argument_match"] == 0.5
    assert report.metrics["chat_no_tool"] == 1.0
    assert [c[0] for c in h.runner.calls] == ["/fake/ping", "/fake/df"]  # read-only tools only


def test_simulated_runner_never_runs_anything():
    result = SimulatedRunner().run(["rm", "-rf", "/"], timeout=1, max_bytes=10)
    assert result.ok and "simulated" in result.stdout
