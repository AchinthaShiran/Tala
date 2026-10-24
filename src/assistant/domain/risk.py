"""Risk classification and approval modes."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    """How much damage a tool can do. Every tool must declare one."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class ApprovalMode(StrEnum):
    """How a tool call is authorised before it runs."""

    AUTO = "auto"  # run without asking
    ASK = "ask"  # yes/no prompt
    CONFIRM = "confirm"  # user must type the tool name
    DENY = "deny"  # never run
