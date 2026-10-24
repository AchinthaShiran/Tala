"""Strict validation and normalisation of LLM-supplied tool arguments."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from assistant.domain import InvalidArgumentsError, ParamSpec, ToolSpec
from assistant.domain.tool import ScalarValue

_TRUE = {"true", "yes", "1", "on"}
_FALSE = {"false", "no", "0", "off"}


def validate_arguments(spec: ToolSpec, raw: Mapping[str, Any]) -> dict[str, ScalarValue]:
    """Return arguments with defaults applied and types coerced, or raise with every problem.

    Small models often send ``"5"`` for an integer, so strings are coerced when unambiguous.
    Anything else that does not fit the declared schema is rejected so the agent can repair it.
    """
    errors: list[str] = []
    unknown = sorted(set(raw) - set(spec.parameters))
    if unknown:
        errors.append(f"unknown argument(s): {', '.join(unknown)}")

    result: dict[str, ScalarValue] = {}
    for name, param in spec.parameters.items():
        if name not in raw or raw[name] is None:
            if param.default is not None:
                result[name] = param.default
            elif param.required:
                errors.append(f"missing required argument '{name}'")
            continue
        try:
            result[name] = _validate_value(name, param, raw[name])
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        raise InvalidArgumentsError(f"invalid arguments for {spec.name}: " + "; ".join(errors))
    return result


def _validate_value(name: str, param: ParamSpec, value: Any) -> ScalarValue:
    coerced = _coerce(name, param, value)
    if param.enum is not None and coerced not in param.enum:
        raise ValueError(f"'{name}' must be one of {list(param.enum)}")
    if isinstance(coerced, str):
        _check_string(name, param, coerced)
    elif isinstance(coerced, int | float) and not isinstance(coerced, bool):
        if param.minimum is not None and coerced < param.minimum:
            raise ValueError(f"'{name}' must be >= {param.minimum:g}")
        if param.maximum is not None and coerced > param.maximum:
            raise ValueError(f"'{name}' must be <= {param.maximum:g}")
    return coerced


def _coerce(name: str, param: ParamSpec, value: Any) -> ScalarValue:
    kind = param.type
    if kind == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
    elif kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
            return value.strip().lower() in _TRUE
    elif kind == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
            return int(value.strip())
    elif kind == "number":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
    raise ValueError(f"'{name}' must be a {kind}, got {type(value).__name__}")


def _check_string(name: str, param: ParamSpec, value: str) -> None:
    if "\x00" in value:
        raise ValueError(f"'{name}' contains a NUL character")
    if param.max_length is not None and len(value) > param.max_length:
        raise ValueError(f"'{name}' is longer than {param.max_length} characters")
    if value.startswith("-") and not param.allow_dash:
        raise ValueError(f"'{name}' must not start with '-' (could be read as a command option)")
    if param.pattern is not None and re.search(param.pattern, value) is None:
        raise ValueError(f"'{name}' does not match the required pattern {param.pattern}")
