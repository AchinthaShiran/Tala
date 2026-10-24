"""The ToolSpec model: a logical capability with per-OS command variants.

A ``ToolSpec`` that constructs successfully satisfies every structural invariant (declared and
used placeholders, constraint consistency, mandatory risk). Softer quality rules live in
``assistant.packs.validator``.
"""

from __future__ import annotations

import codecs
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from assistant.domain.platform import Platform
from assistant.domain.risk import RiskLevel

ScalarValue = str | int | float | bool
ParamType = Literal["string", "integer", "number", "boolean"]

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ParamSpec(_Frozen):
    """One tool parameter, including the constraints that defend against bad LLM output."""

    type: ParamType = "string"
    description: str = ""
    default: ScalarValue | None = None
    optional: bool = False
    enum: tuple[ScalarValue, ...] | None = None
    pattern: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = Field(default=None, gt=0)
    allow_dash: bool = False  # permit string values that start with "-"

    @property
    def required(self) -> bool:
        return self.default is None and not self.optional

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"invalid regex pattern: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _consistent(self) -> ParamSpec:
        numeric = self.type in ("integer", "number")
        if (self.minimum is not None or self.maximum is not None) and not numeric:
            raise ValueError("minimum/maximum only apply to integer/number parameters")
        if (self.pattern is not None or self.max_length is not None) and self.type != "string":
            raise ValueError("pattern/max_length only apply to string parameters")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum is greater than maximum")
        if self.default is not None and not _matches_type(self.default, self.type):
            raise ValueError(f"default {self.default!r} is not a valid {self.type}")
        return self

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        return schema


class ConditionalArgs(_Frozen):
    """Arguments included only when parameter ``when`` is present and not false/empty."""

    when: str
    args: tuple[str, ...]


ArgItem = str | ConditionalArgs


class CommandSpec(_Frozen):
    """An executable plus an argument template. Run without a shell."""

    exe: str = Field(min_length=1)
    args: tuple[ArgItem, ...] = ()

    @field_validator("exe")
    @classmethod
    def _bare_executable(cls, value: str) -> str:
        if any(ch.isspace() for ch in value):
            raise ValueError("exe must be a single executable name or path, without spaces")
        return value


class ToolSpec(_Frozen):
    """A logical tool the assistant may run."""

    name: str
    description: str = Field(min_length=10, max_length=400)
    risk: RiskLevel
    parameters: dict[str, ParamSpec] = Field(default_factory=dict)
    run: dict[Platform, CommandSpec] = Field(min_length=1)
    examples: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    category: str | None = None
    timeout: float = Field(default=30.0, gt=0, le=3600)
    max_output_bytes: int = Field(default=64_000, ge=1_000, le=4_000_000)
    output_encoding: str = "utf-8"
    confirm_message: str | None = None
    # Filled in by the loader:
    pack: str = ""
    source: str = ""

    @field_validator("output_encoding")
    @classmethod
    def _known_codec(cls, value: str) -> str:
        if value.lower() != "oem":
            try:
                codecs.lookup(value)
            except LookupError:
                raise ValueError(f"unknown output_encoding {value!r}") from None
        return value

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("name must match ^[a-z][a-z0-9_]{1,63}$")
        return value

    @field_validator("parameters")
    @classmethod
    def _valid_param_names(cls, value: dict[str, ParamSpec]) -> dict[str, ParamSpec]:
        for param_name in value:
            if not _IDENT_RE.match(param_name):
                raise ValueError(f"parameter name {param_name!r} must match ^[a-z][a-z0-9_]*$")
        return value

    @model_validator(mode="after")
    def _structure(self) -> ToolSpec:
        if self.risk is RiskLevel.DESTRUCTIVE and not self.confirm_message:
            raise ValueError("destructive tools must define confirm_message")
        used: set[str] = set()
        for platform, command in self.run.items():
            used |= self._check_command(platform, command)
        unused = sorted(set(self.parameters) - used)
        if unused:
            raise ValueError(f"parameters declared but never used in any command: {unused}")
        return self

    def _check_command(self, platform: Platform, command: CommandSpec) -> set[str]:
        used: set[str] = set()
        for item in command.args:
            if isinstance(item, ConditionalArgs):
                if item.when not in self.parameters:
                    raise ValueError(
                        f"[{platform}] 'when: {item.when}' is not a declared parameter"
                    )
                used.add(item.when)
                names = {n for arg in item.args for n in PLACEHOLDER_RE.findall(arg)}
                always_present = False
            else:
                names = set(PLACEHOLDER_RE.findall(item))
                always_present = True
            for param in names:
                spec = self.parameters.get(param)
                if spec is None:
                    raise ValueError(
                        f"[{platform}] placeholder {{{param}}} is not a declared parameter"
                    )
                if always_present and not spec.required and spec.default is None:
                    raise ValueError(
                        f"[{platform}] optional parameter '{param}' without a default is used "
                        "unconditionally; wrap it in a 'when' block or give it a default"
                    )
                used.add(param)
        return used

    # -- behaviour ---------------------------------------------------------------------------

    def variant_for(self, platform: Platform) -> CommandSpec | None:
        """Exact platform variant, falling back to ``any``."""
        return self.run.get(platform) or self.run.get(Platform.ANY)

    def supports(self, platform: Platform) -> bool:
        return self.variant_for(platform) is not None

    @property
    def required_params(self) -> tuple[str, ...]:
        return tuple(name for name, spec in self.parameters.items() if spec.required)

    def json_schema(self) -> dict[str, Any]:
        """JSON Schema describing the arguments, as sent to the LLM."""
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {name: spec.json_schema() for name, spec in self.parameters.items()},
            "additionalProperties": False,
        }
        if self.required_params:
            schema["required"] = list(self.required_params)
        return schema

    def retrieval_text(self) -> str:
        """Text indexed for tool selection."""
        pieces = [
            self.name.replace("_", " "),
            self.description,
            " ".join(self.keywords),
            self.category or "",
            " ".join(self.examples),
        ]
        return " ".join(p for p in pieces if p)


def _matches_type(value: ScalarValue, kind: ParamType) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, str)
