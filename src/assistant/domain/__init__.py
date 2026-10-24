"""Pure domain models: no I/O, no framework imports."""

from assistant.domain.errors import (
    AssistantError,
    ConfigError,
    InvalidArgumentsError,
    LLMUnavailableError,
    PackError,
    ToolNotAvailableError,
)
from assistant.domain.events import (
    ApprovalRequest,
    ApprovalRequestedEvent,
    ErrorEvent,
    Event,
    FinalEvent,
    TokenEvent,
    ToolProposedEvent,
    ToolResultEvent,
)
from assistant.domain.execution import ExecutionResult
from assistant.domain.platform import Platform, current_platform
from assistant.domain.risk import ApprovalMode, RiskLevel
from assistant.domain.tool import CommandSpec, ConditionalArgs, ParamSpec, ToolSpec

__all__ = [
    "ApprovalMode",
    "ApprovalRequest",
    "ApprovalRequestedEvent",
    "AssistantError",
    "CommandSpec",
    "ConditionalArgs",
    "ConfigError",
    "ErrorEvent",
    "Event",
    "ExecutionResult",
    "FinalEvent",
    "InvalidArgumentsError",
    "LLMUnavailableError",
    "PackError",
    "ParamSpec",
    "Platform",
    "RiskLevel",
    "TokenEvent",
    "ToolNotAvailableError",
    "ToolProposedEvent",
    "ToolResultEvent",
    "ToolSpec",
    "current_platform",
]
