"""Test doubles: a scripted chat model, a fake command runner and deterministic embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from assistant.domain import ExecutionResult


def tool_call(name: str, args: dict[str, Any] | None = None, call_id: str = "") -> dict[str, Any]:
    return {"name": name, "args": args or {}, "id": call_id or f"call_{name}", "type": "tool_call"}


def ai(content: str = "", *calls: dict[str, Any]) -> AIMessage:
    return AIMessage(content=content, tool_calls=list(calls))


class ScriptedChatModel(BaseChatModel):
    """Returns pre-written replies in order; records every prompt it receives."""

    script: list[Any] = Field(default_factory=list)  # AIMessage | str
    prompts: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        self.bound_tool_names.append([getattr(t, "name", str(t)) for t in tools])
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.prompts.append(list(messages))
        if not self.script:
            raise AssertionError("ScriptedChatModel ran out of scripted replies")
        reply = self.script.pop(0)
        return reply if isinstance(reply, AIMessage) else AIMessage(content=str(reply))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._next(messages)
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
            for i, c in enumerate(reply.tool_calls)
        ]
        yield ChatGenerationChunk(
            message=AIMessageChunk(content=reply.content, tool_call_chunks=chunks)  # type: ignore[arg-type]
        )

    @property
    def calls(self) -> int:
        return len(self.prompts)


class FakeRunner:
    """CommandRunner double: records argv and returns canned output."""

    def __init__(
        self,
        output: str | Callable[[Sequence[str]], str] = "ok",
        exit_code: int = 0,
    ) -> None:
        self._output = output
        self._exit_code = exit_code
        self.calls: list[tuple[str, ...]] = []

    def run(
        self, argv: Sequence[str], *, timeout: float, max_bytes: int, encoding: str = "utf-8"
    ) -> ExecutionResult:
        self.calls.append(tuple(argv))
        text = self._output(argv) if callable(self._output) else self._output
        return ExecutionResult(tuple(argv), self._exit_code, text, "", 0.01)


class HashEmbeddings(Embeddings):
    """Bag-of-words hashing embeddings: lexically similar texts get high cosine similarity."""

    def __init__(self, dim: int = 64, fail: bool = False) -> None:
        self.dim = dim
        self.fail = fail
        self.queries: list[str] = []

    def _vec(self, text: str) -> list[float]:
        if self.fail:
            raise ConnectionError("embedding backend down")
        vec = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._vec(text)
