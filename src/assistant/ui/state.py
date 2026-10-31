"""Toolkit-free presentation state: how service events map to the pet's mood."""

from __future__ import annotations

from enum import Enum

from assistant.domain import (
    ApprovalRequestedEvent,
    ErrorEvent,
    Event,
    FinalEvent,
    TokenEvent,
)


class Mood(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TALKING = "talking"
    ASKING = "asking"  # waiting for the user to approve a tool call
    ERROR = "error"


STATUS_TEXT: dict[Mood, str] = {
    Mood.IDLE: "Ready",
    Mood.THINKING: "Working…",
    Mood.TALKING: "Replying…",
    Mood.ASKING: "Waiting for your approval",
    Mood.ERROR: "Something went wrong",
}


def mood_for(event: Event) -> Mood:
    """The mood a front end should show after ``event``."""
    if isinstance(event, TokenEvent):
        return Mood.TALKING
    if isinstance(event, ApprovalRequestedEvent):
        return Mood.ASKING
    if isinstance(event, ErrorEvent):
        return Mood.ERROR
    if isinstance(event, FinalEvent):
        return Mood.IDLE
    return Mood.THINKING  # a tool was proposed or has produced a result; the model is still going
