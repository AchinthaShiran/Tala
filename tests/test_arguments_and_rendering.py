from __future__ import annotations

from typing import Any

import pytest

from assistant.domain import InvalidArgumentsError, Platform, ToolSpec
from assistant.tools import format_command, render_arguments, validate_arguments


def spec(params: dict[str, Any], args: list[Any]) -> ToolSpec:
    return ToolSpec.model_validate(
        {
            "name": "demo_tool",
            "description": "A demo tool for testing.",
            "risk": "read_only",
            "parameters": params,
            "run": {"any": {"exe": "demo", "args": args}},
            "examples": ["x"],
        }
    )


S = spec(
    {
        "host": {"type": "string", "pattern": r"^[a-z.]+$", "max_length": 12},
        "count": {"type": "integer", "default": 4, "minimum": 1, "maximum": 10},
        "verbose": {"type": "boolean", "default": False},
        "mode": {"type": "string", "optional": True, "enum": ["a", "b"]},
        "ratio": {"type": "number", "optional": True, "minimum": 0, "maximum": 1},
    },
    [
        "-n",
        "{count}",
        "{host}",
        {"when": "verbose", "args": ["-v"]},
        {"when": "mode", "args": ["--mode={mode}"]},
        {"when": "ratio", "args": ["--ratio", "{ratio}"]},
    ],
)


def test_defaults_applied_and_types_coerced():
    assert validate_arguments(S, {"host": "a.b"}) == {"host": "a.b", "count": 4, "verbose": False}
    got = validate_arguments(S, {"host": "a.b", "count": "7", "verbose": "yes", "ratio": "0.5"})
    assert got["count"] == 7 and got["verbose"] is True and got["ratio"] == 0.5


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({}, "missing required argument 'host'"),
        ({"host": "a.b", "count": 0}, "must be >= 1"),
        ({"host": "a.b", "count": 11}, "must be <= 10"),
        ({"host": "a.b", "count": "many"}, "must be a integer"),
        ({"host": "a.b", "count": True}, "must be a integer"),
        ({"host": "-a"}, "must not start with '-'"),
        ({"host": "UPPER"}, "required pattern"),
        ({"host": "a" * 13}, "longer than 12"),
        ({"host": "a.b", "mode": "z"}, "must be one of"),
        ({"host": "a.b", "extra": 1}, "unknown argument"),
        ({"host": "a\x00b"}, "NUL"),
    ],
)
def test_invalid_arguments_report_the_problem(args, message):
    with pytest.raises(InvalidArgumentsError, match=message):
        validate_arguments(S, args)


def test_all_problems_reported_together():
    with pytest.raises(InvalidArgumentsError) as exc:
        validate_arguments(S, {"count": 99, "bogus": 1})
    text = str(exc.value)
    assert "missing required" in text and "<= 10" in text and "unknown" in text


def test_allow_dash_opt_in():
    s = spec({"v": {"type": "string", "allow_dash": True}}, ["{v}"])
    assert validate_arguments(s, {"v": "-x"}) == {"v": "-x"}


def test_none_value_treated_as_missing():
    assert validate_arguments(S, {"host": "a.b", "count": None})["count"] == 4


def test_rendering_applies_conditionals_and_formats():
    args = validate_arguments(S, {"host": "a.b", "verbose": True, "mode": "b", "ratio": 0.25})
    assert render_arguments(S, args, Platform.LINUX) == [
        "-n",
        "4",
        "a.b",
        "-v",
        "--mode=b",
        "--ratio",
        "0.25",
    ]
    bare = validate_arguments(S, {"host": "a.b"})
    assert render_arguments(S, bare, Platform.LINUX) == ["-n", "4", "a.b"]


def test_literal_braces_without_placeholder_are_untouched():
    s = spec({"level": {"type": "string", "default": "W"}}, ["*:{level}", "{not valid}", "{}"])
    assert render_arguments(s, {"level": "E"}, Platform.LINUX) == ["*:E", "{not valid}", "{}"]


def test_boolean_placeholder_renders_lowercase():
    s = spec({"flag": {"type": "boolean", "default": True}}, ["--x={flag}"])
    assert render_arguments(s, {"flag": True}, Platform.LINUX) == ["--x=true"]


def test_format_command_quotes_for_display():
    assert "'a b'" in format_command(["x", "a b"]) or '"a b"' in format_command(["x", "a b"])
