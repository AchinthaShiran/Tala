from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from assistant.cli import app as cli_app
from assistant.domain.branding import HOME_ENV

runner = CliRunner()
GOOD = """
pack: demo
tools:
  - name: say_hello
    description: Print a friendly greeting message.
    risk: read_only
    examples: [say hello, greet me]
    parameters:
      who: {type: string, description: Name, max_length: 20}
    run:
      any: {exe: echo, args: [hello, "{who}"]}
"""


def test_validate_good_pack_exits_zero(tmp_path: Path):
    (tmp_path / "ok.yaml").write_text(GOOD, encoding="utf-8")
    result = runner.invoke(cli_app.app, ["packs", "validate", str(tmp_path)])
    assert result.exit_code == 0 and "1 tools loaded, 0 errors" in result.output


def test_validate_bad_pack_exits_nonzero_and_names_the_problem(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text(GOOD.replace("    risk: read_only\n", ""), encoding="utf-8")
    result = runner.invoke(cli_app.app, ["packs", "validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "say_hello" in result.output and "risk" in result.output


def test_validate_strict_fails_on_warnings(tmp_path: Path):
    (tmp_path / "w.yaml").write_text(
        GOOD.replace("[say hello, greet me]", "[one]"), encoding="utf-8"
    )
    assert runner.invoke(cli_app.app, ["packs", "validate", str(tmp_path)]).exit_code == 0
    assert (
        runner.invoke(cli_app.app, ["packs", "validate", "--strict", str(tmp_path)]).exit_code == 1
    )


def test_validate_builtin_packs_is_clean(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    result = runner.invoke(cli_app.app, ["packs", "validate", "--strict"])
    assert result.exit_code == 0, result.output


def test_packs_list_and_show(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    listed = runner.invoke(cli_app.app, ["packs", "list"])
    assert listed.exit_code == 0 and "disk_free" in listed.output
    shown = runner.invoke(cli_app.app, ["packs", "show", "disk_free"])
    assert shown.exit_code == 0 and '"risk": "read_only"' in shown.output
    assert runner.invoke(cli_app.app, ["packs", "show", "nope"]).exit_code == 1


def test_facts_commands(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    assert runner.invoke(cli_app.app, ["facts", "add", "phone ip", "1.2.3.4"]).exit_code == 0
    assert "phone ip" in runner.invoke(cli_app.app, ["facts", "list"]).output
    assert runner.invoke(cli_app.app, ["facts", "remove", "phone ip"]).exit_code == 0
    assert runner.invoke(cli_app.app, ["facts", "remove", "phone ip"]).exit_code == 1


def test_user_pack_dir_extends_the_assistant(monkeypatch, tmp_path: Path):
    """The headline feature: drop a YAML file in the user pack dir and the tool appears."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    packs = tmp_path / "config" / "packs"
    packs.mkdir(parents=True)
    (packs / "mine.yaml").write_text(GOOD.replace("demo", "mine"), encoding="utf-8")
    assert "say_hello" in runner.invoke(cli_app.app, ["packs", "list", "--all"]).output


def test_audit_with_no_entries(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    assert "No audit entries" in runner.invoke(cli_app.app, ["audit"]).output


def test_validate_prints_the_error_text_not_just_counts(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text("pack: x\ntools: [unclosed", encoding="utf-8")
    result = runner.invoke(cli_app.app, ["packs", "validate", str(tmp_path)])
    assert result.exit_code == 1 and "[error]" in result.output and "bad.yaml" in result.output
