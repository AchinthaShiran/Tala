from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.embeddings import Embeddings
from rich.console import Console
from typer.testing import CliRunner

from assistant.cli import app as cli_app
from assistant.cli.render import ConsoleRenderer
from assistant.config import AgentSettings, EmbeddingSettings, ModelSettings, Settings
from assistant.domain import (
    ApprovalMode,
    ApprovalRequest,
    ApprovalRequestedEvent,
    ConfigError,
    ErrorEvent,
    FinalEvent,
    RiskLevel,
    TokenEvent,
    ToolProposedEvent,
    ToolResultEvent,
)
from assistant.llm import (
    PrefixedEmbeddings,
    build_chat_model,
    build_embeddings,
    register_provider,
)
from assistant.llm import health as health_module
from assistant.service import friendly_error
from tests.support import ScriptedChatModel, ai, tool_call

# -- llm factory -----------------------------------------------------------------------------


def test_chat_model_receives_agent_and_model_settings():
    model = build_chat_model(
        ModelSettings(name="m:1b", num_ctx=4096, keep_alive="5m"),
        AgentSettings(model="x", temperature=0.3, max_tokens=77, think=False),
    )
    assert model.model == "m:1b" and model.num_ctx == 4096 and model.num_predict == 77
    assert model.temperature == 0.3 and model.reasoning is False and model.keep_alive == "5m"


def test_unknown_provider_is_a_config_error():
    with pytest.raises(ConfigError, match="unknown LLM provider"):
        build_chat_model(ModelSettings(provider="nope", name="x"), AgentSettings(model="x"))
    with pytest.raises(ConfigError, match="embedding provider"):
        build_embeddings(EmbeddingSettings(provider="nope"))


def test_custom_provider_can_be_registered():
    register_provider("scripted", lambda m, a: ScriptedChatModel(script=["hi"]))
    model = build_chat_model(ModelSettings(provider="scripted", name="x"), AgentSettings(model="x"))
    assert isinstance(model, ScriptedChatModel)


def test_nomic_embeddings_get_asymmetric_prefixes():
    class Echo(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.docs = texts
            return [[1.0]]

        def embed_query(self, text: str) -> list[float]:
            self.query = text
            return [1.0]

    inner = Echo()
    wrapped = PrefixedEmbeddings(inner, "search_document: ", "search_query: ")
    wrapped.embed_documents(["a"])
    wrapped.embed_query("b")
    assert inner.docs == ["search_document: a"] and inner.query == "search_query: b"
    nomic = build_embeddings(EmbeddingSettings(name="nomic-embed-text"))
    other = build_embeddings(EmbeddingSettings(name="mxbai-embed-large"))
    assert isinstance(nomic, PrefixedEmbeddings) and not isinstance(other, PrefixedEmbeddings)


# -- health ----------------------------------------------------------------------------------


class FakeOllama:
    def __init__(self, models: list[str], caps: list[str], fail: bool = False) -> None:
        self._models, self._caps, self._fail = models, caps, fail

    def __call__(self, host: str, timeout: float) -> FakeOllama:
        return self

    def list(self) -> Any:
        if self._fail:
            raise ConnectionError("refused")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self._models])

    def show(self, name: str) -> Any:
        return SimpleNamespace(capabilities=self._caps)


def checks(monkeypatch: pytest.MonkeyPatch, fake: FakeOllama) -> dict[str, Any]:
    monkeypatch.setattr(health_module.ollama, "Client", fake)
    return {c.name: c for c in health_module.check_backend(Settings())}


def test_health_all_good(monkeypatch):
    installed = ["granite4.1:3b", "gemma4:e2b", "nomic-embed-text:latest"]
    result = checks(monkeypatch, FakeOllama(installed, ["tools"]))
    assert all(c.ok for c in result.values())


def test_health_reports_unreachable_backend(monkeypatch):
    result = checks(monkeypatch, FakeOllama([], [], fail=True))
    (only,) = result.values()
    assert not only.ok and "unreachable" in only.detail


def test_health_reports_missing_models_and_capability(monkeypatch):
    result = checks(monkeypatch, FakeOllama(["gemma4:e2b"], []))
    router = result["model 'router' (granite4.1:3b)"]
    assert not router.ok and "ollama pull granite4.1:3b" in router.detail
    embeddings = result["embeddings (nomic-embed-text)"]
    assert not embeddings.ok and not embeddings.fatal  # keyword search still works
    assert not result["tool calling 'main'"].ok


# -- rendering -------------------------------------------------------------------------------


def renderer(**kw: Any) -> tuple[ConsoleRenderer, io.StringIO]:
    buffer = io.StringIO()
    return ConsoleRenderer(Console(file=buffer, width=120, force_terminal=False), **kw), buffer


def request(
    mode: ApprovalMode = ApprovalMode.ASK, risk: RiskLevel = RiskLevel.MUTATING
) -> ApprovalRequest:
    return ApprovalRequest(
        call_id="c1",
        tool="docker_stop",
        arguments={"container": "web"},
        risk=risk,
        mode=mode,
        command="docker stop [web]",
        message="Careful!",
    )


def test_streamed_tokens_then_final_do_not_duplicate_text():
    r, out = renderer()
    r.begin_turn()
    r.run_events(
        [
            TokenEvent(text="Hello "),
            TokenEvent(text="[bold]world"),
            FinalEvent(text="Hello [bold]world"),
        ]
    )
    text = out.getvalue()
    assert text.count("Hello") == 1 and "[bold]world" in text  # markup in model text is literal


def test_final_without_tokens_is_printed_and_markup_escaped():
    r, out = renderer()
    r.begin_turn()
    r.run_events([FinalEvent(text="use [math]::Round")])
    assert "[math]::Round" in out.getvalue()


def test_tool_events_show_command_and_failures_show_output():
    r, out = renderer()
    r.run_events(
        [
            ToolProposedEvent(
                call_id="1", tool="t", arguments={}, risk=RiskLevel.READ_ONLY, command="x [y] z"
            ),
            ToolResultEvent(
                call_id="1",
                tool="t",
                status="error",
                output="boom [red]",
                exit_code=2,
                duration_ms=5,
            ),
            ErrorEvent(message="bad [thing]"),
        ]
    )
    text = out.getvalue()
    assert "x [y] z" in text and "boom [red]" in text and "bad [thing]" in text


def test_successful_output_hidden_unless_requested():
    event = ToolResultEvent(call_id="1", tool="t", status="ok", output="SECRET-OUT", duration_ms=1)
    quiet, out = renderer()
    quiet.render(event)
    assert "SECRET-OUT" not in out.getvalue()
    loud, out2 = renderer(show_tool_output=True)
    loud.render(event)
    assert "SECRET-OUT" in out2.getvalue()


def test_approval_ask_uses_yes_no(monkeypatch):
    r, out = renderer()
    monkeypatch.setattr("assistant.cli.render.Confirm.ask", lambda *a, **k: True)
    assert r.ask_approvals(ApprovalRequestedEvent(requests=[request()])) == {"c1": True}
    assert "docker stop [web]" in out.getvalue() and "Careful!" in out.getvalue()


@pytest.mark.parametrize(
    ("typed", "expected"), [("docker_stop", True), ("yes", False), ("", False)]
)
def test_approval_confirm_requires_typing_tool_name(monkeypatch, typed, expected):
    r, _ = renderer()
    monkeypatch.setattr("assistant.cli.render.Prompt.ask", lambda *a, **k: typed)
    req = request(ApprovalMode.CONFIRM, RiskLevel.DESTRUCTIVE)
    assert r.ask_approvals(ApprovalRequestedEvent(requests=[req])) == {"c1": expected}


# -- chat loop -------------------------------------------------------------------------------


def test_chat_loop_end_to_end_with_approval(make_harness, monkeypatch):
    h = make_harness(
        {
            "executor": [ai("", tool_call("docker_stop", {"container": "web"})), ai("DONE")],
            "summarizer": ["Stopped it."],
            "chat": ["Hello!"],
        }
    )
    monkeypatch.setattr(cli_app, "create_runtime", lambda config: h.runtime)
    monkeypatch.setattr("assistant.cli.render.Confirm.ask", lambda *a, **k: True)
    session_input = "/help\nhello there\nstop the docker container web\n/history\n/tools\n/exit\n"
    result = CliRunner().invoke(cli_app.app, ["chat", "--session", "t1"], input=session_input)
    out = result.output
    assert result.exit_code == 0, out
    assert "Hello!" in out and "Stopped it." in out and "Commands:" in out
    assert h.runner.calls == [("/fake/docker", "stop", "web")]
    assert "docker_stop" in out  # /tools listing


def test_ask_command_one_shot(make_harness, monkeypatch):
    h = make_harness({"chat": ["Pong."]})
    monkeypatch.setattr(cli_app, "create_runtime", lambda config: h.runtime)
    result = CliRunner().invoke(cli_app.app, ["ask", "hello there"])
    assert result.exit_code == 0 and "Pong." in result.output


def test_chat_reports_config_errors(monkeypatch):
    def boom(config: Any) -> None:
        raise ConfigError("invalid configuration: x")

    monkeypatch.setattr(cli_app, "create_runtime", boom)
    result = CliRunner().invoke(cli_app.app, ["chat"])
    assert result.exit_code == 1 and "invalid configuration" in result.output


# -- error text ------------------------------------------------------------------------------


def test_friendly_errors():
    assert "Ollama" in friendly_error(type("ConnectError", (Exception,), {})("x"))
    assert "Ollama" in friendly_error(RuntimeError("Connection refused by peer"))
    missing = friendly_error(type("ResponseError", (Exception,), {})("model not found"))
    assert "not installed" in missing
    assert friendly_error(ValueError("odd")).startswith("Something went wrong: odd")
