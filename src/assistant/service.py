"""Assistant service: the single front-end contract (see ADR-005).

Front ends call ``send`` / ``resume`` and render the typed events they get back. They never see
LangGraph, prompts, or the policy engine.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StreamMode

from assistant.domain import (
    ApprovalRequest,
    ApprovalRequestedEvent,
    ErrorEvent,
    Event,
    FinalEvent,
    RiskLevel,
    TokenEvent,
    ToolProposedEvent,
    ToolResultEvent,
)

log = logging.getLogger(__name__)

_STREAMING_NODES = frozenset({"chat", "summarizer"})
_RECURSION_LIMIT = 60
_STREAM_MODES: list[StreamMode] = ["messages", "updates"]


@dataclass(frozen=True, slots=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str


class Assistant:
    """Conversation service over a compiled agent graph."""

    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        checkpointer: BaseCheckpointSaver[Any],
    ) -> None:
        self._graph = graph
        self._checkpointer = checkpointer

    # -- public API --------------------------------------------------------------------------

    def send(self, session_id: str, text: str) -> Iterator[Event]:
        """Process a user message. May end with ``ApprovalRequestedEvent`` (call ``resume``)."""
        yield from self._abandon_pending_approval(session_id)
        payload = {"messages": [HumanMessage(content=text)], "session_id": session_id}
        yield from self._stream(session_id, payload)

    def resume(self, session_id: str, decisions: Mapping[str, bool]) -> Iterator[Event]:
        """Answer a pending approval: ``{call_id: approved}``. Missing ids count as denied."""
        yield from self._stream(session_id, Command(resume=dict(decisions)))

    def pending_approval(self, session_id: str) -> ApprovalRequestedEvent | None:
        state = self._graph.get_state(self._config(session_id))
        requests: list[ApprovalRequest] = []
        for task in state.tasks:
            for interrupt in task.interrupts:
                requests.extend(_requests_from(interrupt.value))
        return ApprovalRequestedEvent(requests=requests) if requests else None

    def history(self, session_id: str) -> list[Turn]:
        values = self._graph.get_state(self._config(session_id)).values or {}
        turns: list[Turn] = []
        for message in values.get("messages", []):
            if isinstance(message, HumanMessage):
                turns.append(Turn("user", _content(message)))
            elif isinstance(message, AIMessage) and not message.tool_calls and message.content:
                turns.append(Turn("assistant", _content(message)))
        return turns

    def reset(self, session_id: str) -> None:
        delete = getattr(self._checkpointer, "delete_thread", None)
        if delete is not None:
            delete(session_id)

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _config(session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": _RECURSION_LIMIT}

    def _abandon_pending_approval(self, session_id: str) -> Iterator[Event]:
        """A new message while an approval is open means "no": deny and finish that turn."""
        pending = self.pending_approval(session_id)
        if pending is None:
            return
        denial = {r.call_id: False for r in pending.requests}
        for event in self.resume(session_id, denial):
            if isinstance(event, ToolResultEvent):
                yield event

    def _stream(self, session_id: str, payload: Any) -> Iterator[Event]:
        final_text = ""
        try:
            stream = cast(
                "Iterator[tuple[str, Any]]",
                self._graph.stream(payload, self._config(session_id), stream_mode=_STREAM_MODES),
            )
            for mode, chunk in stream:
                if mode == "messages":
                    token = _token(chunk)
                    if token:
                        yield TokenEvent(text=token)
                    continue
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        requests = [r for item in update for r in _requests_from(item.value)]
                        yield ApprovalRequestedEvent(requests=requests)
                        return
                    final_text = yield from self._on_update(node, update or {}, final_text)
        except Exception as exc:
            log.exception("turn failed")
            yield ErrorEvent(message=friendly_error(exc))
            return
        yield FinalEvent(text=final_text)

    def _on_update(
        self, node: str, update: dict[str, Any], final_text: str
    ) -> Generator[Event, None, str]:
        """Translate one node's state update into events; returns the latest final text."""
        messages: list[BaseMessage] = update.get("messages", [])
        if node == "executor":
            for call in update.get("pending", []):
                yield ToolProposedEvent(
                    call_id=call["id"],
                    tool=call["name"],
                    arguments=call["args"],
                    risk=RiskLevel(call["risk"]),
                    command=call["command"],
                )
        elif node == "run_tools":
            for message in messages:
                if isinstance(message, ToolMessage):
                    yield _tool_result(message)
        if node in _STREAMING_NODES or update.get("next") == "end":
            last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            if last is not None:
                return _content(last)
        return final_text


# -- helpers ---------------------------------------------------------------------------------


def _content(message: BaseMessage) -> str:
    return message.content if isinstance(message.content, str) else str(message.content)


def _token(chunk: Any) -> str:
    message, metadata = chunk
    if (
        isinstance(message, AIMessageChunk)
        and metadata.get("langgraph_node") in _STREAMING_NODES
        and isinstance(message.content, str)
    ):
        return message.content
    return ""


def _requests_from(value: Any) -> list[ApprovalRequest]:
    items = value.get("requests", []) if isinstance(value, dict) else []
    return [ApprovalRequest.model_validate(item) for item in items]


def _tool_result(message: ToolMessage) -> ToolResultEvent:
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    status = artifact.get("status", "ok" if message.status == "success" else "error")
    return ToolResultEvent(
        call_id=message.tool_call_id,
        tool=message.name or "",
        status=status,
        output=str(artifact.get("preview", _content(message))),
        exit_code=artifact.get("exit_code"),
        duration_ms=int(artifact.get("duration_ms", 0)),
    )


def friendly_error(exc: Exception) -> str:
    """User-facing message; connection problems get actionable text."""
    name = type(exc).__name__
    text = str(exc)
    if name in {"ConnectError", "ConnectionError", "ConnectTimeout", "ReadTimeout"} or (
        "connect" in text.lower() and "refused" in text.lower()
    ):
        return (
            "I can't reach the language model (is Ollama running?). Run `lpa doctor` to diagnose."
        )
    if name == "ResponseError" and "not found" in text.lower():
        return f"A configured model is not installed: {text}. Run `lpa doctor`."
    return f"Something went wrong: {text or name}"
