"""Keep the conversation inside the model's context window."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, trim_messages

_CHARS_PER_TOKEN = 3.5
_PER_MESSAGE_OVERHEAD = 6
_OLD_OUTPUT_KEEP_CHARS = 160


def approx_tokens(messages: Sequence[BaseMessage]) -> int:
    """Cheap, model-agnostic token estimate (errs high)."""
    total = 0
    for message in messages:
        content = message.content if isinstance(message.content, str) else str(message.content)
        total += int(len(content) / _CHARS_PER_TOKEN) + _PER_MESSAGE_OVERHEAD
        for call in getattr(message, "tool_calls", None) or []:
            total += int(len(str(call.get("args", ""))) / _CHARS_PER_TOKEN) + 8
    return total


def compact_old_tool_outputs(
    messages: Sequence[BaseMessage], keep_recent_turns: int
) -> list[BaseMessage]:
    """Shrink tool outputs that belong to turns older than the last ``keep_recent_turns``."""
    human_positions = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(human_positions) <= keep_recent_turns:
        return list(messages)
    boundary = (
        human_positions[len(human_positions) - keep_recent_turns]
        if keep_recent_turns
        else len(messages)
    )
    compacted: list[BaseMessage] = []
    for index, message in enumerate(messages):
        if (
            index < boundary
            and isinstance(message, ToolMessage)
            and isinstance(message.content, str)
            and len(message.content) > _OLD_OUTPUT_KEEP_CHARS
        ):
            short = message.content[:_OLD_OUTPUT_KEEP_CHARS].rstrip()
            message = message.model_copy(update={"content": f"{short} … [older output omitted]"})
        compacted.append(message)
    return compacted


def fit_to_budget(messages: Sequence[BaseMessage], budget_tokens: int) -> list[BaseMessage]:
    """Drop the oldest whole turns until the estimate fits. The latest turn is always kept."""
    trimmed = trim_messages(
        list(messages),
        max_tokens=budget_tokens,
        token_counter=approx_tokens,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    last_human = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=None
    )
    if last_human is None:
        return list(trimmed) or list(messages)[-1:]
    if not any(m is messages[last_human] for m in trimmed):
        return list(messages[last_human:])
    return list(trimmed)
