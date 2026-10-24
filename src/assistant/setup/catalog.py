"""The curated set of models the wizard offers (data lives in ``catalog.yaml``)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["light", "balanced", "heavy"]
Role = Literal["chat", "embedding"]
TIERS: tuple[Tier, ...] = ("light", "balanced", "heavy")
DEFAULT_CATALOG = Path(__file__).with_name("catalog.yaml")


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str
    label: str
    role: Role
    tier: Tier
    download_gb: float = Field(gt=0)
    memory_gb: float = Field(gt=0)
    kv_gb_per_8k: float = Field(default=0.0, ge=0)
    tool_calling: bool = True
    router_ok: bool = False
    default_for: Tier | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Catalog:
    models: tuple[ModelEntry, ...]

    def chat_models(self) -> list[ModelEntry]:
        return self._sorted(m for m in self.models if m.role == "chat")

    def router_models(self) -> list[ModelEntry]:
        return self._sorted(m for m in self.models if m.role == "chat" and m.router_ok)

    def embedding_models(self) -> list[ModelEntry]:
        return self._sorted(m for m in self.models if m.role == "embedding")

    def get(self, tag: str) -> ModelEntry | None:
        return next((m for m in self.models if m.tag == tag), None)

    def default_for(self, role: Role, tier: Tier) -> ModelEntry:
        """The model recommended for a tier; falls back to the smallest of that role."""
        candidates = [m for m in self.models if m.role == role]
        exact = [m for m in candidates if m.default_for == tier]
        if exact:
            return exact[0]
        return min(candidates, key=lambda m: m.memory_gb)

    @staticmethod
    def _sorted(models: Iterable[ModelEntry]) -> list[ModelEntry]:
        order = {tier: i for i, tier in enumerate(TIERS)}
        return sorted(models, key=lambda m: (order[m.tier], m.memory_gb))


def load_catalog(path: Path | None = None) -> Catalog:
    raw = yaml.safe_load((path or DEFAULT_CATALOG).read_text(encoding="utf-8"))
    models = tuple(ModelEntry.model_validate(item) for item in raw["models"])
    tags = [m.tag for m in models]
    if len(tags) != len(set(tags)):
        raise ValueError("duplicate model tags in the catalog")
    return Catalog(models)
