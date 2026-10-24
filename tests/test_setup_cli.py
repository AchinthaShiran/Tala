"""`setup` command, first-run offer and the installer scripts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
import yaml
from typer.testing import CliRunner

from assistant.cli import app as cli_app
from assistant.cli import setup_cmd
from assistant.config import load_settings
from assistant.domain.branding import HOME_ENV
from assistant.setup import Hardware

runner = CliRunner()
ROOT = Path(__file__).resolve().parent.parent
CPU_16 = Hardware("Windows", ram_gb=15.7, cpu_threads=16)


class FakeOllama:
    """Stands in for ollama.Client; records pulls."""

    installed: ClassVar[list[str]] = []
    pulled: ClassVar[list[str]] = []
    reachable: ClassVar[bool] = True

    def __init__(self, host: str = "", timeout: float | None = None) -> None:
        self.host = host

    def list(self) -> Any:
        if not FakeOllama.reachable:
            raise ConnectionError("refused")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in FakeOllama.installed])

    def pull(self, model: str, *, stream: bool) -> Any:
        FakeOllama.pulled.append(model)
        yield SimpleNamespace(status="downloading", total=10, completed=5)
        yield SimpleNamespace(status="success", total=10, completed=10)


@pytest.fixture
def env(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    monkeypatch.setattr(setup_cmd, "detect_hardware", lambda: CPU_16)
    monkeypatch.setattr(setup_cmd.ollama, "Client", FakeOllama)
    monkeypatch.setattr(setup_cmd, "check_backend", lambda settings: [])
    FakeOllama.installed = ["gemma4:e2b", "nomic-embed-text:latest"]
    FakeOllama.pulled = []
    FakeOllama.reachable = True
    return tmp_path / "config" / "config.yaml"


def invoke(*args: str, input: str | None = None):
    return runner.invoke(cli_app.app, ["setup", *args], input=input)


def test_check_shows_hardware_and_recommendation_without_writing(env: Path):
    result = invoke("--check")
    assert result.exit_code == 0
    assert "Detected: Windows, 15.7 GB RAM" in result.output
    assert "Gemma 4 E2B" in result.output and "setup" in result.output
    assert not env.exists()


def test_default_setup_writes_a_valid_minimal_config(env: Path):
    result = invoke("--default", "--yes", "--no-pull")
    assert result.exit_code == 0, result.output
    assert env.exists() and "All required models are already downloaded" in result.output
    data = yaml.safe_load(env.read_text(encoding="utf-8"))
    assert data["models"]["router"]["name"] == "gemma4:e2b"  # shares the main model on CPU
    settings = load_settings(env, env={})
    assert settings.models["main"].name == "gemma4:e2b" and settings.embeddings is not None


def test_interactive_menu_default_choice(env: Path):
    result = invoke(input="1\ny\n")  # 1 = default setup, y = save
    assert result.exit_code == 0, result.output
    assert "How would you like to set up?" in result.output and env.exists()


def test_declining_the_final_prompt_changes_nothing(env: Path):
    result = invoke(input="1\nn\n")
    assert result.exit_code == 1 and "Nothing was changed" in result.output
    assert not env.exists()


def test_existing_config_is_merged_and_backed_up(env: Path):
    env.parent.mkdir(parents=True)
    env.write_text("packs:\n  disabled_tools: [kill_process]\n", encoding="utf-8")
    result = invoke("--default", "--yes", "--no-pull")
    assert result.exit_code == 0
    data = yaml.safe_load(env.read_text(encoding="utf-8"))
    assert data["packs"] == {"disabled_tools": ["kill_process"]} and "models" in data
    assert env.with_suffix(".yaml.bak").exists()
    assert "merged into it" in result.output and "backup" in result.output.lower()


def test_missing_models_are_downloaded_with_pull(env: Path):
    FakeOllama.installed = []
    result = invoke("--default", "--yes", "--pull")
    assert result.exit_code == 0, result.output
    assert FakeOllama.pulled == ["gemma4:e2b", "nomic-embed-text"]
    assert "Models to download" in result.output


def test_yes_alone_never_starts_a_large_download(env: Path):
    FakeOllama.installed = []
    result = invoke("--default", "--yes")
    assert result.exit_code == 0 and FakeOllama.pulled == []
    assert "Skipping download" in result.output and "--pull" in result.output


def test_no_pull_prints_the_manual_commands(env: Path):
    FakeOllama.installed = []
    result = invoke("--default", "--yes", "--no-pull")
    assert FakeOllama.pulled == [] and "ollama pull gemma4:e2b" in result.output


def test_unreachable_ollama_is_explained_not_fatal(env: Path):
    FakeOllama.reachable = False
    result = invoke("--default", "--yes", "--no-pull")
    assert result.exit_code == 0 and env.exists()
    assert "Ollama is not reachable" in result.output and "ollama.com/download" in result.output


def test_problems_found_after_setup_are_listed(env: Path, monkeypatch):
    from assistant.llm import HealthCheck

    monkeypatch.setattr(
        setup_cmd,
        "check_backend",
        lambda s: [HealthCheck("model 'main'", False, "missing, run: ollama pull x")],
    )
    result = invoke("--default", "--yes", "--no-pull")
    assert "need attention" in result.output and "ollama pull x" in result.output


def test_conflicting_flags_are_rejected(env: Path):
    assert invoke("--default", "--advanced").exit_code == 1
    both = invoke("--advanced", "--yes")
    assert both.exit_code == 1 and "interactive" in both.output
    assert not env.exists()


# -- first-run offer ---------------------------------------------------------------------------


@pytest.fixture
def first_run(monkeypatch, make_harness, tmp_path: Path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    harness = make_harness({"chat": ["hi"]})
    monkeypatch.setattr(cli_app, "create_runtime", lambda config: harness.runtime)
    calls: list[str] = []
    monkeypatch.setattr(cli_app, "run_setup", lambda *a, **k: calls.append("setup") or 0)
    monkeypatch.setattr(cli_app, "_interactive", lambda: True)
    return SimpleNamespace(calls=calls, marker=tmp_path / "data" / cli_app.SETUP_SKIPPED_MARKER)


def test_first_run_offers_the_wizard_and_runs_it_on_yes(first_run, monkeypatch):
    monkeypatch.setattr(cli_app.Confirm, "ask", lambda *a, **k: True)
    runner.invoke(cli_app.app, ["chat"], input="/exit\n")
    assert first_run.calls == ["setup"] and not first_run.marker.exists()


def test_declining_is_remembered_and_not_asked_again(first_run, monkeypatch):
    asked: list[bool] = []
    monkeypatch.setattr(cli_app.Confirm, "ask", lambda *a, **k: asked.append(True) or False)
    first = runner.invoke(cli_app.app, ["chat"], input="/exit\n")
    runner.invoke(cli_app.app, ["chat"], input="/exit\n")
    assert asked == [True] and first_run.calls == [] and first_run.marker.exists()
    assert "setup" in first.output  # tells the user how to run it later


def test_no_offer_when_not_interactive_or_already_configured(
    first_run, monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(cli_app.Confirm, "ask", lambda *a, **k: pytest.fail("should not ask"))
    monkeypatch.setattr(cli_app, "_interactive", lambda: False)
    runner.invoke(cli_app.app, ["chat"], input="/exit\n")
    monkeypatch.setattr(cli_app, "_interactive", lambda: True)
    config = tmp_path / "config" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("runtime: {}\n", encoding="utf-8")
    runner.invoke(cli_app.app, ["chat"], input="/exit\n")
    assert first_run.calls == []


# -- installers --------------------------------------------------------------------------------


def test_install_sh_parses_and_keeps_names_in_variables():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    for variable in ("APP_NAME=", "COMMAND=", "ENV_PREFIX=", "DEFAULT_PACKAGE="):
        assert variable in text
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no POSIX shell available")
    assert (
        subprocess.run([shell, "-n", str(ROOT / "install.sh")], capture_output=True).returncode == 0
    )


def test_install_ps1_parses_and_keeps_names_in_variables():
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")
    for variable in ("$AppName =", "$Command =", "$EnvPrefix =", "$DefaultPackage ="):
        assert variable in text
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell not available")
    script = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{ROOT / 'install.ps1'}',[ref]$null,[ref]$e); if($e.Count){{exit 1}}"
    )
    assert (
        subprocess.run(
            [powershell, "-NoProfile", "-Command", script], capture_output=True
        ).returncode
        == 0
    )


def test_installers_match_the_branding_module():
    from assistant.domain import branding

    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert f'COMMAND="{branding.COMMAND}"' in sh and f'$Command = "{branding.COMMAND}"' in ps
    assert (
        f'ENV_PREFIX="{branding.ENV_PREFIX}"' in sh
        and f'$EnvPrefix = "{branding.ENV_PREFIX}"' in ps
    )
    assert f'APP_NAME="{branding.APP_NAME}"' in sh and f'$AppName = "{branding.APP_NAME}"' in ps
