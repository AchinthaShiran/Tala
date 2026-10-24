"""Exception hierarchy. Everything the assistant raises on purpose derives from AssistantError."""

from __future__ import annotations


class AssistantError(Exception):
    """Base class for expected, user-presentable errors."""


class PackError(AssistantError):
    """A tool pack is malformed or violates a lint rule."""


class InvalidArgumentsError(AssistantError):
    """Tool arguments failed validation."""


class ToolNotAvailableError(AssistantError):
    """The tool is unknown, or has no runnable variant on this machine."""


class ConfigError(AssistantError):
    """Configuration is invalid."""


class LLMUnavailableError(AssistantError):
    """The language-model backend cannot be reached or lacks a required model."""
