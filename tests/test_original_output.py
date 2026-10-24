"""Summary first, then an offer of the verbatim output of content-heavy tools."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from assistant.config import RuntimeSettings, Settings
from assistant.domain import OFFER_TEXT, FinalEvent, TokenEvent, is_affirmative
from tests.support import FakeRunner, ai, tool_call

SESSION = "s1"
PAGE = "<html><body>Example Domain</body></html>"


def run(h, text: str) -> list:
    return list(h.assistant.send(SESSION, text))


def fetch_harness(make_harness, **runtime):
    settings = Settings(embeddings=None, runtime=RuntimeSettings(fast_path=False, **runtime))
    return make_harness(
        {
            "executor": [ai("", tool_call("http_get", {"url": "https://example.com"})), ai("DONE")],
            "summarizer": ["It is the Example Domain page."],
        },
        settings=settings,
        runner=FakeRunner(PAGE),
    )


def text_of(events: list) -> str:
    return "".join(e.text for e in events if isinstance(e, TokenEvent))


@pytest.mark.parametrize(
    "reply",
    ["yes", "Yes!", "yeah", "y", "sure", "ok", "yes please", "yes, show it", "show it", "show me",
     "original", "the original output", "show me the original", "raw", "full output", "please"],
)  # fmt: skip
def test_short_affirmatives_are_recognised(reply):
    assert is_affirmative(reply)


@pytest.mark.parametrize(
    "reply",
    ["no", "nope", "no thanks", "show me the running processes", "yes and also ping google.com",
     "what is the original price of bitcoin", "", "thanks"],
)  # fmt: skip
def test_other_messages_are_not_affirmatives(reply):
    assert not is_affirmative(reply)


def test_summary_comes_first_and_ends_with_the_offer(make_harness):
    h = fetch_harness(make_harness)
    events = run(h, "fetch example.com")

    streamed = text_of(events)
    assert streamed.startswith("It is the Example Domain page.")
    assert streamed.endswith(OFFER_TEXT)
    assert PAGE not in streamed
    final = events[-1]
    assert isinstance(final, FinalEvent) and final.text.endswith(OFFER_TEXT)


def test_yes_shows_the_stored_output_separately_without_the_model(make_harness):
    h = fetch_harness(make_harness)
    run(h, "fetch example.com")
    calls_before = (h.models["summarizer"].calls, h.models["chat"].calls, len(h.runner.calls))

    events = run(h, "yes")

    shown = text_of(events)
    assert shown == f"Original output of http_get:\n\n{PAGE}"
    assert isinstance(events[-1], FinalEvent) and events[-1].text == shown
    assert (
        h.models["summarizer"].calls,
        h.models["chat"].calls,
        len(h.runner.calls),
    ) == calls_before

    # The raw text is not added to the conversation as assistant speech, and the offer is used up.
    state = h.runtime.assistant._graph.get_state({"configurable": {"thread_id": SESSION}})
    assistant_text = " ".join(
        m.content for m in state.values["messages"] if isinstance(m, AIMessage)
    )
    assert PAGE not in assistant_text and "Showed the original output" in assistant_text
    assert not state.values["offered"]
    again = run(h, "yes")  # nothing is offered any more: this is just a new (chit-chat) message
    assert "Original output of" not in text_of(again)


def test_a_different_request_drops_the_offer(make_harness):
    h = fetch_harness(make_harness)
    h.models["chat"].script.append(AIMessage(content="Hello!"))
    run(h, "fetch example.com")
    run(h, "hello there")
    state = h.runtime.assistant._graph.get_state({"configurable": {"thread_id": SESSION}})
    assert not state.values["offered"]


def test_no_offer_when_disabled_in_settings(make_harness):
    h = fetch_harness(make_harness, offer_original_output=False)
    events = run(h, "fetch example.com")
    assert OFFER_TEXT not in text_of(events)
    assert events[-1].text == "It is the Example Domain page."


def test_ordinary_tools_get_no_offer(make_harness):
    h = make_harness(
        {"executor": [ai("", tool_call("disk_free")), ai("DONE")], "summarizer": ["10G free."]}
    )
    events = run(h, "how much disk space is free")
    assert events[-1].text == "10G free."


def test_offer_tools_are_never_answered_with_raw_direct_output(make_harness):
    h = fetch_harness(make_harness, direct_output_chars=5000)
    events = run(h, "fetch example.com")
    assert events[-1].text.startswith("It is the Example Domain page.")
    assert h.models["summarizer"].calls == 1
