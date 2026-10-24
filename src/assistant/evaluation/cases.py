"""Golden evaluation cases: what the assistant *should* pick for a given request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CASES = Path(__file__).with_name("golden.yaml")


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    expect: tuple[str, ...] = Field(
        description="Acceptable tools; empty means no tool (plain chat)"
    )
    args: dict[str, Any] = Field(default_factory=dict)  # subset the first call must contain

    @field_validator("expect", mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if value in (None, "none", [], ()):
            return ()
        return (value,) if isinstance(value, str) else tuple(value)

    @property
    def expects_tool(self) -> bool:
        return bool(self.expect)


def load_cases(path: Path | None = None) -> list[EvalCase]:
    raw = yaml.safe_load((path or DEFAULT_CASES).read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw["cases"]]
