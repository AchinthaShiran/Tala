from __future__ import annotations

from pathlib import Path

from assistant.domain import Platform
from assistant.packs import PackRoot, Severity, ToolRegistry, load_packs

GOOD = """
pack: demo
version: 1.0.0
tools:
  - name: say_hello
    description: Print a friendly greeting message.
    risk: read_only
    examples: [say hello, greet me]
    parameters:
      who: {type: string, description: Name, max_length: 20}
    run:
      any: {exe: echo, args: ["hello", "{who}"]}
"""


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    return directory


def issues(report, severity=Severity.ERROR):
    return [i for i in report.issues if i.severity is severity]


def test_valid_pack_loads_with_pack_and_source_metadata(tmp_path):
    root = write(tmp_path / "a", "demo.yaml", GOOD)
    report = load_packs([PackRoot(root, "builtin")])
    assert not report.errors
    spec = report.tools["say_hello"]
    assert spec.pack == "demo" and spec.source == "builtin:demo.yaml"


def test_problems_are_reported_with_file_and_tool(tmp_path):
    bad = GOOD.replace("    risk: read_only\n", "").replace("say_hello", "no_risk")
    root = write(tmp_path / "a", "bad.yaml", bad)
    report = load_packs([PackRoot(root, "user")])
    assert not report.tools
    (error,) = report.errors
    assert error.tool == "no_risk" and "risk" in error.message and "bad.yaml" in error.file


def test_one_bad_tool_does_not_block_the_others(tmp_path):
    text = (
        GOOD
        + """
  - name: broken_tool
    description: References an undeclared placeholder.
    risk: read_only
    examples: [x, y]
    run:
      any: {exe: echo, args: ["{ghost}"]}
"""
    )
    report = load_packs([PackRoot(write(tmp_path, "p.yaml", text), "x")])
    assert set(report.tools) == {"say_hello"}
    assert len(report.errors) == 1


def test_malformed_yaml_and_wrong_shape_are_errors_not_crashes(tmp_path):
    write(tmp_path, "broken.yaml", "pack: [unclosed")
    write(tmp_path, "shape.yaml", "tools: []\n")  # missing 'pack'
    write(tmp_path, "scalar.yaml", "just a string")
    report = load_packs([PackRoot(tmp_path, "x")])
    assert len(report.errors) == 3


def test_duplicate_name_in_same_root_is_an_error(tmp_path):
    write(tmp_path, "a.yaml", GOOD)
    write(tmp_path, "b.yaml", GOOD)
    report = load_packs([PackRoot(tmp_path, "x")])
    assert len(report.tools) == 1
    assert any("duplicate" in e.message for e in report.errors)


def test_later_root_overrides_earlier_and_says_so(tmp_path):
    low = write(tmp_path / "low", "p.yaml", GOOD)
    high = write(
        tmp_path / "high", "p.yaml", GOOD.replace("greeting message", "custom override text")
    )
    report = load_packs([PackRoot(low, "builtin"), PackRoot(high, "user")])
    assert "custom override" in report.tools["say_hello"].description
    assert any(i.severity is Severity.INFO and "overrides" in i.message for i in report.issues)


def test_disable_by_pack_and_tool(tmp_path):
    root = write(tmp_path, "p.yaml", GOOD)
    assert not load_packs([PackRoot(root, "x")], disabled_packs=["demo"]).tools
    assert not load_packs([PackRoot(root, "x")], disabled_tools=["say_hello"]).tools


def test_missing_directory_is_fine(tmp_path):
    assert load_packs([PackRoot(tmp_path / "nope", "x")]).issues == []


def test_lint_warnings(tmp_path):
    text = GOOD.replace("examples: [say hello, greet me]", "examples: [only one]").replace(
        "{type: string, description: Name, max_length: 20}", "{type: string}"
    )
    report = load_packs([PackRoot(write(tmp_path, "p.yaml", text), "x")])
    messages = " ".join(i.message for i in issues(report, Severity.WARNING))
    assert "example" in messages and "description" in messages and "constraint" in messages


def test_zero_examples_is_an_error(tmp_path):
    text = GOOD.replace("    examples: [say hello, greet me]\n", "")
    report = load_packs([PackRoot(write(tmp_path, "p.yaml", text), "x")])
    assert not report.tools and any("example" in e.message for e in report.errors)


def test_registry_partitions_by_platform_and_executable(tmp_path):
    text = (
        GOOD
        + """
  - name: windows_only
    description: Only exists on Windows machines here.
    risk: read_only
    examples: [a, b]
    run:
      windows: {exe: winthing}
"""
    )
    report = load_packs([PackRoot(write(tmp_path, "p.yaml", text), "x")])
    registry = ToolRegistry(
        report.tools.values(), Platform.LINUX, which=lambda e: "/bin/echo" if e == "echo" else None
    )
    assert set(registry.available) == {"say_hello"}
    assert registry.unavailable["windows_only"].reason == "no variant for linux"

    win = ToolRegistry(report.tools.values(), Platform.WINDOWS, which=lambda e: None)
    assert win.unavailable["say_hello"].reason == "executable 'echo' not found on PATH"
    assert "say_hello" not in win and len(win) == 0


def test_unknown_output_encoding_is_rejected_at_load(tmp_path):
    text = GOOD.replace(
        "    risk: read_only\n", "    risk: read_only\n    output_encoding: klingon-9\n"
    )
    report = load_packs([PackRoot(write(tmp_path, "p.yaml", text), "x")])
    assert not report.tools and any("output_encoding" in e.message for e in report.errors)
    ok = GOOD.replace("    risk: read_only\n", "    risk: read_only\n    output_encoding: oem\n")
    assert "say_hello" in load_packs([PackRoot(write(tmp_path / "ok", "p.yaml", ok), "x")]).tools
