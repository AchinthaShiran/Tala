"""The fast path skips the executor model for decisive, argument-free, read-only requests."""

from __future__ import annotations

import pytest

from assistant.agent.fastpath import pick_fast_tool
from assistant.config import RetrievalSettings, RuntimeSettings, Settings, builtin_packs_dir
from assistant.domain import FinalEvent, Platform, ToolProposedEvent, ToolResultEvent
from assistant.packs import PackRoot, ToolRegistry, load_packs
from assistant.retrieval import Confidence, Hit, SearchResult
from tests.support import ai, tool_call

SESSION = "fast"
REGISTRY = ToolRegistry(
    load_packs([PackRoot(builtin_packs_dir(), "b")]).tools.values(),
    Platform.LINUX,
    which=lambda exe: f"/fake/{exe}",
)
CFG = RetrievalSettings()


def hit(name, *, sim=None, terms=0, named=False):
    return Hit(name, 0.0, 0.0, sim, terms, named)


def result(*hits, confidence=Confidence.STRONG):
    return SearchResult(tuple(hits), confidence)


# -- the decision ----------------------------------------------------------------------------


def test_picks_a_clear_argument_free_read_only_match():
    r = result(hit("disk_free", sim=0.8), hit("memory_usage", sim=0.6))
    assert pick_fast_tool(r, REGISTRY, CFG, margin=0.05) == "disk_free"


@pytest.mark.parametrize(
    "r",
    [
        result(hit("disk_free", sim=0.8), confidence=Confidence.WEAK),  # not confident
        result(hit("disk_free", sim=0.65)),  # below strong similarity
        result(hit("disk_free", sim=0.8), hit("memory_usage", sim=0.78)),  # runner-up too close
        result(hit("ping_host", sim=0.9)),  # needs a host argument
        result(hit("docker_stop", sim=0.9)),  # mutating
        result(hit("kill_process", sim=0.9)),  # destructive
        result(hit("not_a_tool", sim=0.9)),  # unknown/unavailable
        result(),  # nothing found
    ],
)
def test_declines_when_any_condition_fails(r):
    assert pick_fast_tool(r, REGISTRY, CFG, margin=0.05) is None


def test_keyword_only_mode_is_stricter():
    ok = result(hit("disk_free", terms=2, named=True), hit("memory_usage", terms=1))
    assert pick_fast_tool(ok, REGISTRY, CFG, margin=0.05) == "disk_free"
    assert (
        pick_fast_tool(result(hit("disk_free", terms=1, named=True)), REGISTRY, CFG, margin=0.05)
        is None
    )
    tie = result(hit("disk_free", terms=2, named=True), hit("memory_usage", terms=2, named=True))
    assert pick_fast_tool(tie, REGISTRY, CFG, margin=0.05) is None
    assert pick_fast_tool(result(hit("disk_free", terms=3)), REGISTRY, CFG, margin=0.05) is None


# -- in the graph ----------------------------------------------------------------------------


def fast_settings(**runtime):
    return Settings(embeddings=None, runtime=RuntimeSettings(fast_path=True, **runtime))


def run(h, text):
    return list(h.assistant.send(SESSION, text))


def test_fast_path_runs_the_tool_without_calling_the_executor_model(make_harness):
    h = make_harness({"summarizer": ["10G free."]}, settings=fast_settings())
    events = run(h, "how much disk space is left")

    assert h.models["executor"].calls == 0
    assert h.runner.calls == [("/fake/df", "-h")]
    kinds = [e.type for e in events]
    assert kinds[:2] == ["tool_proposed", "tool_result"] and isinstance(events[-1], FinalEvent)
    assert isinstance(events[0], ToolProposedEvent) and events[0].tool == "disk_free"
    assert isinstance(events[1], ToolResultEvent) and events[1].status == "ok"
    assert h.audit.entries[0].approved_by == "auto"


def test_fast_path_history_is_valid_for_the_next_turn(make_harness):
    h = make_harness({"summarizer": ["10G free."], "chat": ["Hello!"]}, settings=fast_settings())
    run(h, "how much disk space is left")
    assert run(h, "hello there")[-1].text == "Hello!"  # tool call/result pairing was well formed
    assert h.models["chat"].calls == 1


def test_requests_needing_arguments_still_use_the_executor(make_harness):
    h = make_harness(
        {
            "executor": [ai("", tool_call("ping_host", {"host": "example.com"}))],
            "summarizer": ["up"],
        },
        settings=fast_settings(),
    )
    run(h, "ping example.com")
    assert h.models["executor"].calls == 1


def test_multi_step_requests_use_the_executor(make_harness):
    h = make_harness(
        {"executor": [ai("", tool_call("disk_free")), ai("DONE")], "summarizer": ["ok"]},
        settings=fast_settings(),
    )
    run(h, "check disk space then show uptime")
    assert h.models["executor"].calls >= 1


def test_fast_path_can_be_disabled(make_harness):
    h = make_harness(
        {"executor": [ai("", tool_call("disk_free"))], "summarizer": ["ok"]},
        settings=Settings(embeddings=None, runtime=RuntimeSettings(fast_path=False)),
    )
    run(h, "how much disk space is left")
    assert h.models["executor"].calls == 1


def test_policy_still_applies_to_fast_path_tools(make_harness):
    """Only read-only tools qualify, but the policy engine remains the gate (e.g. deny override)."""
    from assistant.config import SafetySettings
    from assistant.domain import ApprovalMode

    settings = Settings(
        embeddings=None,
        runtime=RuntimeSettings(fast_path=True),
        safety=SafetySettings(tool_overrides={"disk_free": ApprovalMode.DENY}),
    )
    h = make_harness({"summarizer": ["blocked"]}, settings=settings)
    events = run(h, "how much disk space is left")
    assert h.runner.calls == []
    assert any(isinstance(e, ToolResultEvent) and e.status == "denied" for e in events)


def test_chit_chat_after_a_tool_request_does_not_rerun_the_tool(make_harness):
    """Short follow-ups borrow the previous message only when they carry real content words."""
    h = make_harness(
        {"summarizer": ["10G free."], "chat": ["Hi!", "You're welcome!"]}, settings=fast_settings()
    )
    run(h, "how much disk space is left")
    assert run(h, "hello there")[-1].text == "Hi!"
    assert run(h, "thanks!")[-1].text == "You're welcome!"
    assert len(h.runner.calls) == 1


def test_content_follow_up_still_borrows_context():
    from langchain_core.messages import AIMessage, HumanMessage

    from assistant.agent.nodes import _routing_query

    history = [
        HumanMessage(content="what is my ip address"),
        AIMessage(content="x"),
        HumanMessage(content="the mac one?"),
    ]
    assert _routing_query(history) == "what is my ip address the mac one?"
    greeting = [*history[:2], HumanMessage(content="thanks a lot")]
    assert _routing_query(greeting) == "thanks a lot"
