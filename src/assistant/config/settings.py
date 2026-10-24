"""Typed, layered application settings: defaults < config file < environment < overrides."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from assistant.domain import ApprovalMode, ConfigError, RiskLevel
from assistant.domain.branding import SETTINGS_ENV_PREFIX as ENV_PREFIX

AGENT_NAMES = ("router", "chat", "executor", "summarizer")


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSettings(_Section):
    provider: str = "ollama"
    name: str
    num_ctx: int = Field(default=8192, ge=512)
    keep_alive: str | None = "30m"
    base_url: str = "http://localhost:11434"
    request_timeout: float = Field(default=120.0, gt=0)


class EmbeddingSettings(_Section):
    provider: str = "ollama"
    name: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


class AgentSettings(_Section):
    model: str
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    think: bool = False
    prompt: str | None = None  # overrides the built-in system prompt


class RetrievalSettings(_Section):
    top_k: int = Field(default=6, ge=1, le=30)
    min_similarity: float = Field(default=0.55, ge=0, le=1)
    strong_similarity: float = Field(default=0.70, ge=0, le=1)
    corroborated_similarity: float = Field(default=0.60, ge=0, le=1)
    min_coverage: float = Field(default=0.5, ge=0, le=1)
    use_embeddings: bool = True


class SafetySettings(_Section):
    modes: dict[RiskLevel, ApprovalMode] = Field(
        default_factory=lambda: {
            RiskLevel.READ_ONLY: ApprovalMode.AUTO,
            RiskLevel.MUTATING: ApprovalMode.ASK,
            RiskLevel.DESTRUCTIVE: ApprovalMode.CONFIRM,
        }
    )
    tool_overrides: dict[str, ApprovalMode] = Field(default_factory=dict)
    pack_overrides: dict[str, ApprovalMode] = Field(default_factory=dict)
    allow_auto_mutating: bool = False
    audit_log: bool = True

    @model_validator(mode="after")
    def _no_auto_destructive(self) -> SafetySettings:
        if self.modes.get(RiskLevel.DESTRUCTIVE) is ApprovalMode.AUTO:
            raise ValueError("destructive tools can never be set to 'auto'")
        if self.modes.get(RiskLevel.MUTATING) is ApprovalMode.AUTO and not self.allow_auto_mutating:
            raise ValueError("mutating=auto requires safety.allow_auto_mutating: true")
        return self


class RuntimeSettings(_Section):
    max_steps: int = Field(default=3, ge=1, le=10)
    max_repairs: int = Field(default=2, ge=0, le=5)
    history_budget_ratio: float = Field(default=0.6, gt=0.1, le=0.95)
    tool_output_chars: int = Field(default=6000, ge=500)
    recent_turns_full_tools: int = Field(default=1, ge=0)


class PackSettings(_Section):
    dirs: list[Path] = Field(default_factory=list)
    disabled_packs: list[str] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)


def _default_models() -> dict[str, ModelSettings]:
    return {
        "router": ModelSettings(name="granite4.1:3b", num_ctx=2048),
        "main": ModelSettings(name="gemma4:e2b", num_ctx=8192),
    }


def _default_agents() -> dict[str, AgentSettings]:
    return {
        "router": AgentSettings(model="router", temperature=0.0, max_tokens=8),
        "chat": AgentSettings(model="main", temperature=0.6, max_tokens=400),
        "executor": AgentSettings(model="main", temperature=0.1, max_tokens=512),
        "summarizer": AgentSettings(model="main", temperature=0.2, max_tokens=500),
    }


class Settings(_Section):
    models: dict[str, ModelSettings] = Field(default_factory=_default_models)
    embeddings: EmbeddingSettings | None = Field(default_factory=EmbeddingSettings)
    agents: dict[str, AgentSettings] = Field(default_factory=_default_agents)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    packs: PackSettings = Field(default_factory=PackSettings)
    data_dir: Path | None = None  # overrides the platform data directory

    @model_validator(mode="after")
    def _agents_reference_models(self) -> Settings:
        missing_agents = [a for a in AGENT_NAMES if a not in self.agents]
        if missing_agents:
            raise ValueError(f"missing agent definitions: {missing_agents}")
        for name, agent in self.agents.items():
            if agent.model not in self.models:
                raise ValueError(f"agent '{name}' references unknown model '{agent.model}'")
        return self


def load_settings(
    config_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Merge defaults, YAML file, ``<PREFIX>__A__B=value`` env vars and explicit overrides."""
    merged: dict[str, Any] = Settings().model_dump(mode="json")
    if config_file is not None and config_file.exists():
        try:
            loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read config {config_file}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"config {config_file} must be a mapping at top level")
        _deep_merge(merged, loaded)
    _deep_merge(merged, _env_overrides(env if env is not None else os.environ))
    if overrides:
        _deep_merge(merged, dict(overrides))
    try:
        return Settings.model_validate(merged)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"invalid configuration: {details}") from exc


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in env.items():
        if not key.upper().startswith(ENV_PREFIX):
            continue
        path = [part.lower() for part in key[len(ENV_PREFIX) :].split("__") if part]
        if not path:
            continue
        node = result
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = yaml.safe_load(value)
    return result


def _deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
