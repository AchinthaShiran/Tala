"""Typed events: the only contract between the assistant service and any front end."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from assistant.domain.risk import ApprovalMode, RiskLevel


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True)


class ApprovalRequest(_Event):
    """A tool call waiting for the user's decision."""

    call_id: str
    tool: str
    arguments: dict[str, Any]
    risk: RiskLevel
    mode: ApprovalMode
    command: str  # exact resolved command line
    message: str | None = None  # pack-provided warning for destructive tools


class TokenEvent(_Event):
    type: Literal["token"] = "token"
    text: str


class ToolProposedEvent(_Event):
    type: Literal["tool_proposed"] = "tool_proposed"
    call_id: str
    tool: str
    arguments: dict[str, Any]
    risk: RiskLevel
    command: str


class ApprovalRequestedEvent(_Event):
    type: Literal["approval_requested"] = "approval_requested"
    requests: list[ApprovalRequest]


class ToolResultEvent(_Event):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    tool: str
    status: Literal["ok", "error", "timeout", "denied"]
    output: str
    exit_code: int | None = None
    duration_ms: int = 0


class FinalEvent(_Event):
    type: Literal["final"] = "final"
    text: str


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    message: str


Event = Annotated[
    TokenEvent
    | ToolProposedEvent
    | ApprovalRequestedEvent
    | ToolResultEvent
    | FinalEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
