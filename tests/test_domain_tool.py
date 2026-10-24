from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from assistant.domain import Platform, RiskLevel, ToolSpec


def make(**overrides: Any) -> ToolSpec:
    base: dict[str, Any] = {
        "name": "demo_tool",
        "description": "A demo tool for testing purposes.",
        "risk": "read_only",
        "parameters": {"host": {"type": "string", "description": "h"}},
        "run": {"any": {"exe": "demo", "args": ["{host}"]}},
        "examples": ["demo"],
    }
    base.update(overrides)
    return ToolSpec.model_validate(base)


def test_valid_tool_builds_json_schema():
    spec = make(
        parameters={
            "host": {"type": "string", "description": "h", "pattern": "^a$", "max_length": 5},
            "n": {"type": "integer", "default": 3, "minimum": 1, "maximum": 9},
        },
        run={"any": {"exe": "demo", "args": ["{host}", "{n}"]}},
    )
    schema = spec.json_schema()
    assert schema["required"] == ["host"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["n"] == {
        "type": "integer",
        "default": 3,
        "minimum": 1,
        "maximum": 9,
    }
    assert schema["properties"]["host"]["maxLength"] == 5


def test_risk_is_mandatory():
    with pytest.raises(ValidationError, match="risk"):
        ToolSpec.model_validate(
            {
                "name": "demo_tool",
                "description": "A demo tool for testing.",
                "run": {"any": {"exe": "x"}},
            }
        )


def test_destructive_requires_confirm_message():
    with pytest.raises(ValidationError, match="confirm_message"):
        make(risk="destructive", parameters={}, run={"any": {"exe": "demo"}})
    assert (
        make(
            risk="destructive",
            confirm_message="careful",
            parameters={},
            run={"any": {"exe": "demo"}},
        ).risk
        is RiskLevel.DESTRUCTIVE
    )


def test_undeclared_placeholder_rejected():
    with pytest.raises(ValidationError, match="not a declared parameter"):
        make(run={"any": {"exe": "demo", "args": ["{nope}"]}})


def test_unused_parameter_rejected():
    with pytest.raises(ValidationError, match="never used"):
        make(
            parameters={"host": {"type": "string"}, "extra": {"type": "string"}},
            run={"any": {"exe": "demo", "args": ["{host}"]}},
        )


def test_optional_without_default_must_be_conditional():
    params = {"flag": {"type": "string", "optional": True}}
    with pytest.raises(ValidationError, match="unconditionally"):
        make(parameters=params, run={"any": {"exe": "demo", "args": ["{flag}"]}})
    ok = make(
        parameters=params,
        run={"any": {"exe": "demo", "args": [{"when": "flag", "args": ["--f", "{flag}"]}]}},
    )
    assert ok.required_params == ()


def test_conditional_on_unknown_param_rejected():
    with pytest.raises(ValidationError, match="when: ghost"):
        make(run={"any": {"exe": "demo", "args": ["{host}", {"when": "ghost", "args": ["x"]}]}})


def test_param_constraints_must_match_type():
    with pytest.raises(ValidationError, match="only apply"):
        make(parameters={"host": {"type": "string", "minimum": 1}})
    with pytest.raises(ValidationError, match="not a valid integer"):
        make(
            parameters={"n": {"type": "integer", "default": "x"}},
            run={"any": {"exe": "d", "args": ["{n}"]}},
        )
    with pytest.raises(ValidationError, match="invalid regex"):
        make(parameters={"host": {"type": "string", "pattern": "("}})


def test_bad_names_rejected():
    with pytest.raises(ValidationError):
        make(name="Bad-Name")
    with pytest.raises(ValidationError):
        make(parameters={"Bad": {"type": "string"}}, run={"any": {"exe": "d", "args": ["{Bad}"]}})
    with pytest.raises(ValidationError, match="spaces"):
        make(run={"any": {"exe": "my tool", "args": ["{host}"]}})


def test_variant_selection_prefers_exact_platform():
    spec = make(parameters={}, run={"windows": {"exe": "win"}, "any": {"exe": "generic"}})
    assert spec.variant_for(Platform.WINDOWS).exe == "win"
    assert spec.variant_for(Platform.LINUX).exe == "generic"
    only_win = make(parameters={}, run={"windows": {"exe": "win"}})
    assert not only_win.supports(Platform.LINUX)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        make(surprise=True)


def test_retrieval_text_contains_all_searchable_fields():
    spec = make(keywords=["alpha"], category="beta", examples=["gamma delta"])
    text = spec.retrieval_text()
    assert all(word in text for word in ("demo tool", "alpha", "beta", "gamma delta"))
