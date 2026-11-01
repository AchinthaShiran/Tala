"""Toolkit-free presentation state: how service events map to the pet's mood and emotion."""

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
    """What the assistant is doing (driven by the service events)."""

    IDLE = "idle"
    THINKING = "thinking"
    TALKING = "talking"
    ASKING = "asking"  # waiting for the user to approve a tool call
    ERROR = "error"


class Emotion(Enum):
    """How the pet feels: a short-lived expression layered over the mood."""

    NEUTRAL = "neutral"  # the face follows the mood
    HAPPY = "happy"  # finished a reply, was clicked, was dropped gently
    LOVE = "love"  # petted for a while, or double-clicked
    SURPRISED = "surprised"  # the pointer arrived, picked up, woken up
    SAD = "sad"  # something went wrong
    CURIOUS = "curious"  # waiting for an answer from the user
    DIZZY = "dizzy"  # shaken about
    SLEEPY = "sleepy"  # nobody around for a while
    SLEEPING = "sleeping"
    TIRED = "tired"  # the battery is low
    CHARGING = "charging"  # just plugged in: happy, with sparks


STATUS_TEXT: dict[Mood, str] = {
    Mood.IDLE: "Ready",
    Mood.THINKING: "Working…",
    Mood.TALKING: "Replying…",
    Mood.ASKING: "Waiting for your approval",
    Mood.ERROR: "Something went wrong",
}

# Face shown for a mood when no transient emotion is active.
MOOD_EMOTION: dict[Mood, Emotion] = {
    Mood.ERROR: Emotion.SAD,
    Mood.ASKING: Emotion.CURIOUS,
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


def emotion_for(event: Event) -> tuple[Emotion, float] | None:
    """A brief reaction (emotion, seconds) to an event, or None."""
    if isinstance(event, FinalEvent) and event.text:
        return Emotion.HAPPY, 2.5
    if isinstance(event, ApprovalRequestedEvent):
        return Emotion.SURPRISED, 1.0
    return None
