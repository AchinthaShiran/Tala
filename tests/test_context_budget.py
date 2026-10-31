"""Tool output must fit the model's context window (a prompt that overflows loses its start)."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from assistant.config import ModelSettings, RuntimeSettings, Settings
from assistant.domain import FinalEvent
from tests.support import FakeRunner, ai, tool_call

SESSION = "ctx"
HUGE = "|   +---folder\n" * 2000  # symbol-heavy, like `tree /F`


def tool_output(h) -> str:
    state = h.runtime.assistant._graph.get_state({"configurable": {"thread_id": SESSION}})
    return next(m.content for m in state.values["messages"] if isinstance(m, ToolMessage))


def run(make_harness, num_ctx: int) -> str:
    settings = Settings(
        embeddings=None,
        models={
            "router": ModelSettings(name="r", num_ctx=num_ctx),
            "main": ModelSettings(name="m", num_ctx=num_ctx),
        },
        runtime=RuntimeSettings(fast_path=False, tool_output_chars=6000),
    )
    h = make_harness(
        {"executor": [ai("", tool_call("disk_free")), ai("DONE")], "summarizer": ["ok"]},
        settings=settings,
        runner=FakeRunner(HUGE),
    )
    events = list(h.assistant.send(SESSION, "how much disk space is free"))
    assert isinstance(events[-1], FinalEvent)
    return tool_output(h)


def test_small_context_window_shrinks_the_output_the_model_sees(make_harness):
    small = run(make_harness, num_ctx=2048)
    # ~0.8 characters per context token, plus the fixed wrapper text
    assert len(small) < 1900


def test_large_context_window_keeps_the_configured_limit(make_harness):
    large = run(make_harness, num_ctx=16384)
    assert 5000 < len(large) < 6500
