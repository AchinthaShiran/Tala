"""LangGraph node implementations. Each node is a small method over injected dependencies."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.types import interrupt

from assistant.agent import prompts
from assistant.agent.fastpath import pick_fast_tool
from assistant.agent.state import AgentState, PendingCall
from assistant.config import Settings
from assistant.domain import (
    ApprovalMode,
    ApprovalRequest,
    AssistantError,
    ExecutionResult,
    RiskLevel,
)
from assistant.memory import FactStore, approx_tokens, compact_old_tool_outputs, fit_to_budget
from assistant.packs import ToolRegistry
from assistant.retrieval import Confidence, ToolIndex, content_tokens
from assistant.safety import (
    AuditEntry,
    AuditLog,
    PolicyContext,
    PolicyEngine,
    fence_tool_output,
)
from assistant.tools import ToolExecutor

log = logging.getLogger(__name__)

_SEQUENCE_WORDS = re.compile(r"\b(then|afterwards?|after that|next|followed by|and also)\b", re.I)
MAX_CALLS_PER_MESSAGE = 5
MAX_PARALLEL_READS = 4
PREVIEW_CHARS = 2000
_MIN_HISTORY_TOKENS = 512


@dataclass
class AgentDeps:
    """Everything the nodes need, injected by the composition root."""

    settings: Settings
    models: dict[str, BaseChatModel]  # keyed by agent name
    index: ToolIndex
    registry: ToolRegistry
    executor: ToolExecutor
    policy: PolicyEngine
    audit: AuditLog
    os_name: str
    facts: FactStore | None = None
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def tool(self, name: str) -> BaseTool:
        if name not in self._tools:
            self._tools[name] = self.executor.to_langchain_tool(self.registry.get(name))
        return self._tools[name]


class AgentNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self._d = deps

    # -- shared helpers ----------------------------------------------------------------------

    def _system(self, agent: str) -> SystemMessage:
        override = self._d.settings.agents[agent].prompt
        facts = self._d.facts.render() if self._d.facts else ""
        text = prompts.with_context(
            override or prompts.DEFAULTS[agent],
            os_name=self._d.os_name,
            cwd=os.getcwd(),
            facts=facts,
        )
        return SystemMessage(content=text)

    def _history(
        self, agent: str, messages: Sequence[BaseMessage], reserved_tokens: int = 0
    ) -> list[BaseMessage]:
        cfg = self._d.settings
        agent_cfg = cfg.agents[agent]
        window = cfg.models[agent_cfg.model].num_ctx
        budget = int(window * cfg.runtime.history_budget_ratio) - reserved_tokens
        budget = max(budget - (agent_cfg.max_tokens or 0), _MIN_HISTORY_TOKENS)
        compacted = compact_old_tool_outputs(messages, cfg.runtime.recent_turns_full_tools)
        return fit_to_budget(compacted, budget)

    def _prompt(self, agent: str, state: AgentState, reserved_tokens: int = 0) -> list[BaseMessage]:
        system = self._system(agent)
        reserved = reserved_tokens + approx_tokens([system])
        return [system, *self._history(agent, state["messages"], reserved)]

    # -- route -------------------------------------------------------------------------------

    def route(self, state: AgentState) -> dict[str, Any]:
        reset: dict[str, Any] = {
            "steps": 0,
            "repairs": 0,
            "untrusted_seen": False,
            "pending": [],
            "approved": [],
            "denied": {},
            "candidates": [],
            "fast_tool": "",
        }
        query = _routing_query(state["messages"])
        reset["multi_step"] = self._wants_follow_ups(query)
        available = set(self._d.registry.available)
        if not available or not query:
            return {**reset, "next": "chat"}

        result = self._d.index.search(query, allowed=available)
        reset["candidates"] = result.names
        if result.confidence is Confidence.STRONG:
            runtime = self._d.settings.runtime
            fast = (
                pick_fast_tool(
                    result,
                    self._d.registry,
                    self._d.settings.retrieval,
                    margin=runtime.fast_path_margin,
                )
                if runtime.fast_path and not reset["multi_step"]
                else None
            )
            if fast:
                return {**reset, "fast_tool": fast, "next": "fast"}
            return {**reset, "next": "executor"}
        if result.confidence is Confidence.NONE:
            return {**reset, "next": "chat"}
        return {**reset, "next": "executor" if self._llm_says_act(query) else "chat"}

    def _llm_says_act(self, query: str) -> bool:
        try:
            reply = self._d.models["router"].invoke(
                [self._system("router"), HumanMessage(content=query)]
            )
        except Exception as exc:
            log.warning("router model failed (%s); assuming an action is wanted", exc)
            return True
        text = _text(reply).strip().lower()
        return not (text.startswith("chat") or ("chat" in text and "act" not in text))

    # -- chat / summarizer ---------------------------------------------------------------------

    def chat(self, state: AgentState) -> dict[str, Any]:
        reply = self._d.models["chat"].invoke(self._prompt("chat", state))
        return {"messages": [_plain(reply)]}

    def summarize(self, state: AgentState) -> dict[str, Any]:
        direct = self._direct_answer(state["messages"])
        if direct is not None:
            return {"messages": [AIMessage(content=direct)]}
        reply = self._d.models["summarizer"].invoke(self._prompt("summarizer", state))
        return {"messages": [_plain(reply)]}

    def _wants_follow_ups(self, query: str) -> bool:
        """Whether another executor round may be needed after the first tool results.

        Each extra round costs a full model call before the answer starts, so single-step
        requests (the vast majority) skip it unless configured otherwise.
        """
        mode = self._d.settings.runtime.followups
        if mode == "always":
            return True
        return mode == "auto" and _SEQUENCE_WORDS.search(query) is not None

    def _direct_answer(self, messages: Sequence[BaseMessage]) -> str | None:
        """Raw output of a single successful read-only call, when small enough (skips the model)."""
        limit = self._d.settings.runtime.direct_output_chars
        if limit <= 0:
            return None
        last_human = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
        )
        results = [m for m in messages[last_human + 1 :] if isinstance(m, ToolMessage)]
        if len(results) != 1 or not isinstance(results[0].artifact, dict):
            return None
        result = results[0]
        spec = self._d.registry.available.get(result.name or "")
        text = str(result.artifact.get("preview", ""))
        if (
            spec is None
            or spec.risk is not RiskLevel.READ_ONLY
            or result.artifact.get("status") != "ok"
            or not text.strip()
            or len(text) > limit
        ):
            return None
        return text.strip()

    # -- executor ----------------------------------------------------------------------------

    def fast_path(self, state: AgentState) -> dict[str, Any]:
        """Run the tool retrieval picked, without asking the executor model for a call."""
        name = state.get("fast_tool", "")
        try:
            prepared = self._d.executor.prepare(name, {})
        except AssistantError:
            return {"next": "executor"}  # fall back to the normal path
        call_id = f"call_{uuid4().hex[:12]}"
        ai = AIMessage(
            content="", tool_calls=[{"name": name, "args": {}, "id": call_id, "type": "tool_call"}]
        )
        pending = PendingCall(
            id=call_id,
            name=name,
            args=dict(prepared.arguments),
            command=prepared.command,
            risk=prepared.spec.risk.value,
            mode=ApprovalMode.AUTO.value,
        )
        return {"messages": [ai], "pending": [pending], "repairs": 0, "next": "authorize"}

    def execute_plan(self, state: AgentState) -> dict[str, Any]:
        candidates = [n for n in state.get("candidates", []) if n in self._d.registry]
        if not candidates:
            return {"next": "chat"}
        tools = [self._d.tool(name) for name in candidates]
        schema_tokens = sum(len(json.dumps(t.tool_call_schema)) for t in tools) // 3
        model = self._d.models["executor"].bind_tools(tools)
        reply = model.invoke(self._prompt("executor", state, reserved_tokens=schema_tokens))
        ai = _with_unique_ids(reply)

        steps = state.get("steps", 0)
        if not ai.tool_calls:
            return {"next": "summarizer" if steps > 0 else "chat"}

        pending, errors = self._validate_calls(ai, set(candidates))
        if not errors:
            return {"messages": [ai], "pending": pending, "repairs": 0, "next": "authorize"}

        repairs = state.get("repairs", 0)
        feedback = [
            ToolMessage(
                content=errors[c["id"] or ""],
                tool_call_id=c["id"] or "",
                name=c["name"],
                status="error",
            )
            for c in ai.tool_calls
        ]
        if repairs < self._d.settings.runtime.max_repairs:
            return {"messages": [ai, *feedback], "repairs": repairs + 1, "next": "executor"}
        giveup = AIMessage(
            content="I couldn't build a valid tool call for that request. "
            "Please rephrase it or give the exact values."
        )
        return {"messages": [ai, *feedback, giveup], "next": "end"}

    def _validate_calls(
        self, ai: AIMessage, offered: set[str]
    ) -> tuple[list[PendingCall], dict[str, str]]:
        """Return (pending, errors). ``errors`` is keyed by call id for *every* call when any fails."""
        pending: list[PendingCall] = []
        errors: dict[str, str] = {}
        if len(ai.tool_calls) > MAX_CALLS_PER_MESSAGE:
            note = f"too many tool calls at once (max {MAX_CALLS_PER_MESSAGE}); request fewer"
            return [], {c["id"] or "": note for c in ai.tool_calls}
        for call in ai.tool_calls:
            call_id, name = call["id"] or "", call["name"]
            if name not in offered:
                errors[call_id] = (
                    f"tool '{name}' is not available; choose one of: {sorted(offered)}"
                )
                continue
            try:
                prepared = self._d.executor.prepare(name, call["args"])
            except AssistantError as exc:
                errors[call_id] = str(exc)
                continue
            pending.append(
                PendingCall(
                    id=call_id,
                    name=name,
                    args=dict(prepared.arguments),
                    command=prepared.command,
                    risk=prepared.spec.risk.value,
                    mode=ApprovalMode.AUTO.value,
                )
            )
        if errors:
            skipped = "not executed because another call in the same message was invalid"
            for call in ai.tool_calls:
                errors.setdefault(call["id"] or "", skipped)
            return [], errors
        return pending, {}

    # -- authorize ---------------------------------------------------------------------------

    def authorize(self, state: AgentState) -> dict[str, Any]:
        """Apply policy; pause for the user when needed. Pure before ``interrupt`` (re-run on resume)."""
        ctx = PolicyContext(untrusted_output_seen=state.get("untrusted_seen", False))
        approved: list[str] = []
        denied: dict[str, str] = {}
        to_ask: list[PendingCall] = []
        updated: list[PendingCall] = []

        for call in state.get("pending", []):
            spec = self._d.registry.get(call["name"])
            decision = self._d.policy.decide(spec, ctx)
            call = PendingCall(**{**call, "mode": decision.mode.value})
            updated.append(call)
            if decision.mode is ApprovalMode.DENY:
                denied[call["id"]] = f"blocked by policy ({decision.reason})"
            elif decision.mode is ApprovalMode.AUTO:
                approved.append(call["id"])
            else:
                to_ask.append(call)

        if to_ask:
            requests = [
                ApprovalRequest(
                    call_id=c["id"],
                    tool=c["name"],
                    arguments=c["args"],
                    risk=RiskLevel(c["risk"]),
                    mode=ApprovalMode(c["mode"]),
                    command=c["command"],
                    message=self._d.registry.get(c["name"]).confirm_message,
                ).model_dump(mode="json")
                for c in to_ask
            ]
            answer = interrupt({"requests": requests})
            decisions = answer if isinstance(answer, dict) else {}
            for call in to_ask:
                if decisions.get(call["id"]) is True:
                    approved.append(call["id"])
                else:
                    denied[call["id"]] = "declined by the user"
        return {"pending": updated, "approved": approved, "denied": denied}

    # -- run ---------------------------------------------------------------------------------

    def run_tools(self, state: AgentState) -> dict[str, Any]:
        pending = state.get("pending", [])
        denied = state.get("denied", {})
        runnable = [c for c in pending if c["id"] not in denied]
        results = self._run_all(runnable)

        messages: list[ToolMessage] = []
        session = state.get("session_id", "")
        for call in pending:
            if call["id"] in denied:
                messages.append(self._denied_message(call, denied[call["id"]], session))
            else:
                messages.append(self._result_message(call, results[call["id"]], session))

        steps = state.get("steps", 0) + 1
        stop = (
            bool(denied)
            or steps >= self._d.settings.runtime.max_steps
            or not state.get("multi_step", False)
        )
        return {
            "messages": messages,
            "steps": steps,
            "untrusted_seen": True,
            "pending": [],
            "approved": [],
            "denied": {},
            "next": "summarizer" if stop else "executor",
        }

    def _run_all(self, calls: list[PendingCall]) -> dict[str, ExecutionResult | str]:
        def run_one(call: PendingCall) -> tuple[str, ExecutionResult | str]:
            try:
                message = self._d.tool(call["name"]).invoke(
                    {
                        "name": call["name"],
                        "args": call["args"],
                        "id": call["id"],
                        "type": "tool_call",
                    }
                )
                artifact = getattr(message, "artifact", None)
                if isinstance(artifact, ExecutionResult):
                    return call["id"], artifact
                return call["id"], str(message.content)
            except Exception as exc:
                return call["id"], f"Error: {exc}"

        all_read_only = all(c["risk"] == RiskLevel.READ_ONLY.value for c in calls)
        if len(calls) > 1 and all_read_only:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_READS) as pool:
                return dict(pool.map(run_one, calls))
        return dict(run_one(c) for c in calls)

    def _result_message(
        self, call: PendingCall, result: ExecutionResult | str, session: str
    ) -> ToolMessage:
        if isinstance(result, ExecutionResult):
            text, status, code, ms, truncated = (
                result.render(),
                result.status,
                result.exit_code,
                int(result.duration_s * 1000),
                result.truncated,
            )
            argv = result.argv
        else:
            text, status, code, ms, truncated, argv = result, "error", None, 0, False, ()
        self._d.audit.record(
            AuditEntry(
                session=session,
                tool=call["name"],
                argv=tuple(argv) or (call["command"],),
                mode=call["mode"],
                approved_by="auto" if call["mode"] == ApprovalMode.AUTO.value else "user",
                status=status,
                exit_code=code,
                duration_ms=ms,
                truncated=truncated,
            )
        )
        fenced = fence_tool_output(
            call["name"], call["id"], text, max_chars=self._d.settings.runtime.tool_output_chars
        )
        return ToolMessage(
            content=fenced,
            tool_call_id=call["id"],
            name=call["name"],
            status="success" if status == "ok" else "error",
            artifact={
                "status": status,
                "exit_code": code,
                "duration_ms": ms,
                "preview": text[:PREVIEW_CHARS],
                "command": call["command"],
            },
        )

    def _denied_message(self, call: PendingCall, reason: str, session: str) -> ToolMessage:
        self._d.audit.record(
            AuditEntry(
                session=session,
                tool=call["name"],
                argv=(call["command"],),
                mode=call["mode"],
                approved_by="denied",
                status="denied",
            )
        )
        return ToolMessage(
            content=f"Execution denied: {reason}. The command was not run.",
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
            artifact={
                "status": "denied",
                "exit_code": None,
                "duration_ms": 0,
                "preview": reason,
                "command": call["command"],
            },
        )


# -- module helpers --------------------------------------------------------------------------


def _text(message: BaseMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


def _plain(message: BaseMessage) -> AIMessage:
    """Keep only the answer text (drops reasoning and provider metadata from history)."""
    return AIMessage(content=_text(message).strip() or "…")


def _routing_query(messages: Sequence[BaseMessage]) -> str:
    """Latest user text. A short follow-up with real content words ("and the other adapter?")
    borrows the previous user message for context; pure chit-chat ("thanks") never does."""
    humans = [_text(m) for m in messages if isinstance(m, HumanMessage)]
    if not humans:
        return ""
    latest = humans[-1]
    if len(latest.split()) < 4 and len(humans) > 1 and content_tokens(latest):
        return f"{humans[-2]} {latest}"
    return latest


def _with_unique_ids(reply: BaseMessage) -> AIMessage:
    if not isinstance(reply, AIMessage):
        return AIMessage(content=_text(reply))
    calls: list[Any] = []
    seen: set[str] = set()
    for call in reply.tool_calls:
        call_id = call.get("id") or ""
        if not call_id or call_id in seen:
            call_id = f"call_{uuid4().hex[:12]}"
        seen.add(call_id)
        calls.append({**call, "id": call_id, "args": call.get("args") or {}})
    return AIMessage(content=reply.content, tool_calls=calls)
