"""What the user picked in the wizard, and how it becomes real settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from assistant.config import (
    EmbeddingSettings,
    ModelSettings,
    RetrievalSettings,
    RuntimeSettings,
    SafetySettings,
    Settings,
)
from assistant.domain import ApprovalMode, RiskLevel
from assistant.setup.catalog import ModelEntry

ROUTER_CTX = 2048  # the router only classifies one short message
DIRECT_OUTPUT_CHARS = 600


@dataclass(frozen=True, slots=True)
class SafetyProfile:
    key: str
    label: str
    detail: str


SAFETY_PROFILES = (
    SafetyProfile(
        "default",
        "Default: read-only tools run, changes ask, destructive actions need typing the tool name",
        "Recommended.",
    ),
    SafetyProfile(
        "strict",
        "Strict: ask before every tool, even read-only ones",
        "Safest, but slower to use; every request prompts.",
    ),
    SafetyProfile(
        "relaxed",
        "Relaxed: also run state-changing tools without asking (destructive still confirm)",
        "Not recommended. A wrong or manipulated model could change your system unprompted.",
    ),
)


@dataclass(frozen=True, slots=True)
class SetupChoices:
    main: ModelEntry
    router: ModelEntry | None  # None: the main model also does routing (saves memory)
    embeddings: ModelEntry | None  # None: keyword-only tool search
    num_ctx: int = 8192
    keep_alive: str = "30m"
    safety: str = "default"
    fast_path: bool = True
    direct_output: bool = False
    audit_log: bool = True


def _safety(profile: str) -> SafetySettings:
    if profile == "strict":
        return SafetySettings(
            modes={
                RiskLevel.READ_ONLY: ApprovalMode.ASK,
                RiskLevel.MUTATING: ApprovalMode.ASK,
                RiskLevel.DESTRUCTIVE: ApprovalMode.CONFIRM,
            }
        )
    if profile == "relaxed":
        return SafetySettings(
            modes={
                RiskLevel.READ_ONLY: ApprovalMode.AUTO,
                RiskLevel.MUTATING: ApprovalMode.AUTO,
                RiskLevel.DESTRUCTIVE: ApprovalMode.CONFIRM,
            },
            allow_auto_mutating=True,
        )
    return SafetySettings()


def build_settings(choices: SetupChoices) -> Settings:
    """Full, validated settings for the chosen options."""
    router = choices.router or choices.main
    separate_router = choices.router is not None and choices.router.tag != choices.main.tag
    models = {
        "router": ModelSettings(
            name=router.tag,
            num_ctx=ROUTER_CTX if separate_router else choices.num_ctx,
            keep_alive=choices.keep_alive,
        ),
        "main": ModelSettings(
            name=choices.main.tag, num_ctx=choices.num_ctx, keep_alive=choices.keep_alive
        ),
    }
    safety = _safety(choices.safety).model_copy(update={"audit_log": choices.audit_log})
    return Settings(
        models=models,
        embeddings=EmbeddingSettings(name=choices.embeddings.tag) if choices.embeddings else None,
        retrieval=RetrievalSettings(use_embeddings=choices.embeddings is not None),
        safety=safety,
        runtime=RuntimeSettings(
            fast_path=choices.fast_path,
            direct_output_chars=DIRECT_OUTPUT_CHARS if choices.direct_output else 0,
        ),
    )


def minimal_overrides(settings: Settings, base: Settings | None = None) -> dict[str, Any]:
    """Only the values that differ from the defaults, so future default improvements still apply."""
    return _diff(settings.model_dump(mode="json"), (base or Settings()).model_dump(mode="json"))


def _diff(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for key, value in new.items():
        if isinstance(value, dict) and isinstance(old.get(key), dict):
            nested = _diff(value, old[key])
            if nested:
                changed[key] = nested
        elif value != old.get(key):
            changed[key] = value
    return changed
