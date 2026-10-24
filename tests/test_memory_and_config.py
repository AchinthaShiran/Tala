from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistant.config import Settings, default_paths, load_settings
from assistant.domain import ConfigError
from assistant.domain.branding import HOME_ENV
from assistant.domain.branding import SETTINGS_ENV_PREFIX as ENV_PREFIX
from assistant.memory import FactStore, approx_tokens, compact_old_tool_outputs, fit_to_budget

# -- history -------------------------------------------------------------------------------------


def turn(i: int, tool_text: str = "x" * 1000) -> list:
    return [
        HumanMessage(content=f"question {i}"),
        AIMessage(
            content="", tool_calls=[{"name": "t", "args": {}, "id": f"c{i}", "type": "tool_call"}]
        ),
        ToolMessage(content=tool_text, tool_call_id=f"c{i}", name="t"),
        AIMessage(content=f"answer {i}"),
    ]


def test_old_tool_outputs_are_compacted_recent_kept():
    messages = turn(1) + turn(2)
    out = compact_old_tool_outputs(messages, keep_recent_turns=1)
    old, recent = out[2], out[6]
    assert len(old.content) < 250 and "older output omitted" in old.content
    assert recent.content == "x" * 1000
    assert messages[2].content == "x" * 1000  # input untouched
    assert old.tool_call_id == "c1"


def test_compaction_noop_when_few_turns():
    messages = turn(1)
    assert [m.content for m in compact_old_tool_outputs(messages, 1)] == [
        m.content for m in messages
    ]


def test_fit_to_budget_drops_oldest_whole_turns_and_keeps_latest():
    messages = [m for i in range(1, 8) for m in turn(i, "y" * 600)]
    fitted = fit_to_budget(messages, budget_tokens=800)
    assert approx_tokens(fitted) <= 800 + 50
    assert isinstance(fitted[0], HumanMessage)  # never starts mid-turn
    assert fitted[-1].content == "answer 7"
    assert len(fitted) < len(messages)


def test_latest_human_message_survives_even_over_budget():
    messages = [*turn(1), HumanMessage(content="z" * 20000)]
    fitted = fit_to_budget(messages, budget_tokens=100)
    assert fitted and fitted[-1].content.startswith("zzz")


def test_system_message_not_required_for_fitting():
    assert (
        fit_to_budget([SystemMessage(content="s"), HumanMessage(content="hi")], 500)[-1].content
        == "hi"
    )


# -- facts -----------------------------------------------------------------------------------


def test_fact_store_roundtrip_and_render(tmp_path):
    store = FactStore(tmp_path / "f.sqlite")
    store.remember("Phone IP", "192.168.1.20:5555")
    store.remember("phone ip", "10.0.0.5:5555")  # update, case-insensitive key
    store.remember("editor", "vim")
    assert store.all() == {"editor": "vim", "phone ip": "10.0.0.5:5555"}
    assert "- phone ip: 10.0.0.5:5555" in store.render()
    assert store.forget("EDITOR") and not store.forget("editor")
    with pytest.raises(ValueError):
        store.remember(" ", "x")
    assert len(store.render(max_chars=10)) <= 40
    store.close()


# -- settings --------------------------------------------------------------------------------


def test_defaults_are_valid_and_consistent():
    s = Settings()
    assert set(s.agents) == {"router", "chat", "executor", "summarizer"}
    assert all(a.model in s.models for a in s.agents.values())
    assert s.agents["router"].temperature == 0 and s.agents["executor"].think is False


def test_layering_file_then_env_then_overrides(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "models:\n  main:\n    name: file-model\nruntime:\n  max_steps: 5\n", encoding="utf-8"
    )
    env = {
        f"{ENV_PREFIX}MODELS__MAIN__NUM_CTX": "16384",
        f"{ENV_PREFIX}RUNTIME__MAX_STEPS": "7",
        "OTHER": "x",
    }
    s = load_settings(cfg, env=env, overrides={"retrieval": {"top_k": 9}})
    assert s.models["main"].name == "file-model"  # file overrides default
    assert s.models["main"].num_ctx == 16384  # env adds
    assert s.runtime.max_steps == 7  # env beats file
    assert s.retrieval.top_k == 9  # explicit override
    assert s.models["router"].name == "granite4.1:3b"  # untouched default survives


def test_missing_file_means_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.yaml", env={}) == Settings()


@pytest.mark.parametrize(
    "content",
    [
        "agents:\n  chat:\n    model: ghost\n",
        "runtime:\n  max_steps: 0\n",
        "mystery_key: 1\n",
        "safety:\n  modes:\n    destructive: auto\n",
        "- a list\n",
    ],
)
def test_invalid_config_raises_config_error(tmp_path, content):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(cfg, env={})


def test_paths_honour_assistant_home(monkeypatch, tmp_path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    paths = default_paths()
    assert paths.config_file == tmp_path / "config" / "config.yaml"
    assert paths.checkpoints_db.parent == tmp_path / "data"
    paths.ensure()
    assert paths.user_packs_dir.parent.is_dir()
