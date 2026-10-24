"""LangGraph state."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class PendingCall(TypedDict):
    """A validated tool call awaiting authorisation/execution."""

    id: str
    name: str
    args: dict[str, Any]
    command: str  # exact resolved command line
    risk: str
    mode: str  # approval mode applied


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    candidates: list[str]  # tool names offered to the executor this turn
    pending: list[PendingCall]
    approved: list[str]  # call ids cleared to run
    denied: dict[str, str]  # call id -> reason
    fast_tool: str  # tool chosen by retrieval alone (fast path), else empty
    multi_step: bool  # request may need more than one executor round
    steps: int  # tool rounds executed this turn
    repairs: int  # consecutive invalid-call repairs
    untrusted_seen: bool  # tool output entered the context this turn
    next: str  # routing hint written by nodes
