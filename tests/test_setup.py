"""Setup wizard: hardware, catalog, recommendations, warnings, settings, config writing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from assistant.config import Settings, load_settings
from assistant.setup import (
    Catalog,
    Hardware,
    Option,
    SetupChoices,
    assess,
    build_settings,
    detect_hardware,
    estimate_memory_gb,
    installed_tags,
    load_catalog,
    minimal_overrides,
    missing_tags,
    needed_tags,
    pull_model,
    recommend,
    recommend_tier,
    run_wizard,
    write_config,
)
from assistant.setup.hardware import parse_meminfo, parse_nvidia_smi

CATALOG = load_catalog()
CPU_16 = Hardware("Windows", ram_gb=15.7, cpu_threads=16)
CPU_4 = Hardware("Linux", ram_gb=4.0, cpu_threads=4)
GPU_8 = Hardware("Linux", ram_gb=32, cpu_threads=16, gpu_name="RTX 3060", vram_gb=8)
GPU_12 = Hardware("Linux", ram_gb=32, cpu_threads=16, gpu_name="RTX 3060", vram_gb=12)
GPU_24 = Hardware("Linux", ram_gb=64, cpu_threads=16, gpu_name="RTX 4090", vram_gb=24)
MAC_32 = Hardware("macOS", ram_gb=32, cpu_threads=10, unified_memory=True)


def tag(name: str):
    model = CATALOG.get(name)
    assert model is not None, name
    return model


# -- hardware ----------------------------------------------------------------------------------


def test_parsers():
    assert parse_meminfo("MemTotal:       16384000 kB\nMemFree: 1 kB") == pytest.approx(
        15.625, abs=0.01
    )
    assert parse_meminfo("nothing") is None
    smi = "NVIDIA GeForce RTX 3060, 12288\nNVIDIA GeForce GT 710, 2048\n"
    assert parse_nvidia_smi(smi) == ("NVIDIA GeForce RTX 3060", 12.0)
    assert parse_nvidia_smi("") is None and parse_nvidia_smi("garbage line") is None


def test_detect_nvidia_machine():
    hw = detect_hardware(
        platform_name="linux",
        machine="x86_64",
        which=lambda exe: "/usr/bin/nvidia-smi",
        ram_probe=lambda: 32.0,
        smi_probe=lambda: "NVIDIA GeForce RTX 3060, 12288",
    )
    assert (hw.system, hw.ram_gb, hw.vram_gb, hw.gpu_name) == (
        "Linux",
        32.0,
        12.0,
        "NVIDIA GeForce RTX 3060",
    )
    assert hw.accelerated and hw.budget_gb == 12.0
    assert "RTX 3060" in hw.describe()


def test_detect_apple_silicon_uses_unified_memory():
    hw = detect_hardware(
        platform_name="darwin", machine="arm64", which=lambda exe: None, ram_probe=lambda: 32.0
    )
    assert hw.system == "macOS" and hw.unified_memory and hw.accelerated
    assert hw.budget_gb == pytest.approx(22.4)
    assert "unified" in hw.describe()


def test_detect_cpu_only_windows_and_budget():
    hw = detect_hardware(
        platform_name="win32", machine="AMD64", which=lambda exe: None, ram_probe=lambda: 16.0
    )
    assert hw.system == "Windows" and not hw.accelerated and hw.vram_gb is None
    assert hw.budget_gb == pytest.approx(11.2) and "no supported GPU" in hw.describe()


def test_detection_never_raises_when_probes_fail():
    def boom() -> Any:
        raise OSError("no access")

    hw = detect_hardware(
        platform_name="linux", which=lambda exe: "/x/nvidia-smi", ram_probe=boom, smi_probe=boom
    )
    assert hw.ram_gb is None and hw.vram_gb is None and hw.budget_gb is None
    assert not hw.accelerated


# -- catalog -----------------------------------------------------------------------------------


def test_catalog_is_well_formed():
    tags = [m.tag for m in CATALOG.models]
    assert len(tags) == len(set(tags))
    assert CATALOG.chat_models() and CATALOG.embedding_models() and CATALOG.router_models()
    assert {m.tier for m in CATALOG.chat_models()} == {"light", "balanced", "heavy"}
    assert all(m.tool_calling for m in CATALOG.chat_models())
    for tier in ("light", "balanced", "heavy"):
        assert CATALOG.default_for("chat", tier).role == "chat"
    tiers = [m.tier for m in CATALOG.chat_models()]
    assert tiers == sorted(tiers, key=("light", "balanced", "heavy").index)


def test_application_defaults_exist_in_the_catalog():
    """Guards against the wizard and the built-in defaults drifting apart."""
    defaults = Settings()
    assert CATALOG.get(defaults.models["main"].name)
    assert CATALOG.get(defaults.models["router"].name)
    assert defaults.embeddings and CATALOG.get(defaults.embeddings.name)


def test_duplicate_tags_are_rejected(tmp_path: Path):
    entry = {
        "tag": "a:1",
        "label": "A",
        "role": "chat",
        "tier": "light",
        "download_gb": 1,
        "memory_gb": 1,
    }
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({"models": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_catalog(path)


# -- recommendations ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hardware", "tier"),
    [
        (CPU_16, "light"),
        (CPU_4, "light"),
        (Hardware("Linux", ram_gb=128), "light"),  # lots of RAM but no GPU: CPU is slow
        (Hardware("Linux"), "light"),  # nothing known
        (GPU_8, "light"),
        (GPU_12, "balanced"),
        (GPU_24, "heavy"),
        (MAC_32, "balanced"),
    ],
)
def test_recommended_tier(hardware, tier):
    assert recommend_tier(hardware) == tier


def test_recommendation_details():
    cpu = recommend(CPU_16, CATALOG)
    assert (
        cpu.main.tag == "gemma4:e2b"
        and cpu.router is None
        and cpu.embeddings.tag == "nomic-embed-text"
    )
    assert recommend(CPU_4, CATALOG).num_ctx == 4096
    big = recommend(GPU_24, CATALOG)
    assert big.main.tier == "heavy" and big.router is not None  # room for a separate router
    assert recommend(GPU_12, CATALOG).router is None  # not enough headroom to justify one


def test_memory_estimate_adds_distinct_models_and_context_cache():
    base = SetupChoices(main=tag("gemma4:e2b"), router=None, embeddings=None, num_ctx=8192)
    assert estimate_memory_gb(base) == pytest.approx(5.7)
    assert estimate_memory_gb(replace(base, num_ctx=16384)) == pytest.approx(6.1)
    with_extras = replace(base, router=tag("granite4.1:3b"), embeddings=tag("nomic-embed-text"))
    assert estimate_memory_gb(with_extras) == pytest.approx(5.7 + 2.6 + 0.5 + 0.1, abs=0.15)
    same_router = replace(base, router=tag("gemma4:e2b"))
    assert estimate_memory_gb(same_router) == estimate_memory_gb(base)


def advice_levels(choices: SetupChoices, hw: Hardware) -> dict[str, str]:
    return {a.text: a.level for a in assess(choices, hw)}


def levels(choices: SetupChoices, hw: Hardware) -> list[str]:
    return [a.level for a in assess(choices, hw)]


def test_default_recommendation_raises_no_resource_warnings():
    rec = recommend(CPU_16, CATALOG)
    assert [a for a in assess(rec, CPU_16) if a.level in ("warn", "danger")] == []


def test_heavy_model_on_modest_hardware_is_a_serious_warning():
    choices = replace(recommend(CPU_16, CATALOG), main=tag("gpt-oss:20b"))
    found = assess(choices, CPU_16)
    texts = " ".join(a.text for a in found)
    assert "danger" in [a.level for a in found]
    assert "swapping" in texts and "large model" in texts


def test_larger_model_without_gpu_warns_about_speed():
    choices = replace(recommend(CPU_16, CATALOG), main=tag("gemma4:e4b"))
    assert any("noticeably slower" in a.text for a in assess(choices, CPU_16))


def test_heavy_model_on_a_big_gpu_still_warns_but_is_not_dangerous():
    choices = replace(recommend(GPU_24, CATALOG), main=tag("gpt-oss:20b"))
    found = assess(choices, GPU_24)
    assert "danger" not in [a.level for a in found]
    assert any("large model" in a.text for a in found)


def test_context_keep_alive_and_safety_warnings():
    rec = recommend(CPU_16, CATALOG)
    assert any("16384" in a.text for a in assess(replace(rec, num_ctx=16384), CPU_16))
    assert any("idle" in a.text for a in assess(replace(rec, keep_alive="-1"), CPU_16))
    assert any(
        a.level == "danger" and "without asking" in a.text
        for a in assess(replace(rec, safety="relaxed"), CPU_16)
    )
    assert any("every tool" in a.text for a in assess(replace(rec, safety="strict"), CPU_16))
    assert any("keyword-only" in a.text for a in assess(replace(rec, embeddings=None), CPU_16))
    separate = replace(rec, router=tag("granite4.1:3b"))
    assert any("separate router" in a.text for a in assess(separate, CPU_16))


def test_model_without_tool_calling_is_flagged():
    from assistant.setup.catalog import ModelEntry

    no_tools = ModelEntry(
        tag="x:1",
        label="X",
        role="chat",
        tier="light",
        download_gb=1,
        memory_gb=1,
        tool_calling=False,
    )
    found = assess(replace(recommend(CPU_16, CATALOG), main=no_tools), CPU_16)
    assert any(a.level == "danger" and "tool calling" in a.text for a in found)


# -- choices to settings -----------------------------------------------------------------------


@pytest.mark.parametrize("safety", ["default", "strict", "relaxed"])
@pytest.mark.parametrize("router", [None, "granite4.1:3b"])
@pytest.mark.parametrize("embeddings", [None, "nomic-embed-text", "mxbai-embed-large"])
def test_every_combination_builds_valid_settings(safety, router, embeddings):
    choices = SetupChoices(
        main=tag("gemma4:e4b"),
        router=tag(router) if router else None,
        embeddings=tag(embeddings) if embeddings else None,
        safety=safety,
        direct_output=True,
    )
    settings = build_settings(choices)
    assert settings.models["main"].name == "gemma4:e4b"
    assert (settings.embeddings is None) == (embeddings is None)
    assert settings.retrieval.use_embeddings == (embeddings is not None)
    assert settings.runtime.direct_output_chars == 600


def test_router_shares_the_main_model_when_not_separate():
    settings = build_settings(replace(recommend(CPU_16, CATALOG), num_ctx=4096))
    assert settings.models["router"].name == settings.models["main"].name
    assert settings.models["router"].num_ctx == settings.models["main"].num_ctx == 4096


def test_separate_router_gets_a_small_context():
    settings = build_settings(replace(recommend(CPU_16, CATALOG), router=tag("granite4.1:3b")))
    assert settings.models["router"].name == "granite4.1:3b"
    assert settings.models["router"].num_ctx == 2048


def test_safety_profiles_map_to_policies():
    from assistant.domain import ApprovalMode, RiskLevel

    rec = recommend(CPU_16, CATALOG)
    strict = build_settings(replace(rec, safety="strict")).safety
    assert strict.modes[RiskLevel.READ_ONLY] is ApprovalMode.ASK
    relaxed = build_settings(replace(rec, safety="relaxed")).safety
    assert relaxed.allow_auto_mutating and relaxed.modes[RiskLevel.MUTATING] is ApprovalMode.AUTO
    assert relaxed.modes[RiskLevel.DESTRUCTIVE] is ApprovalMode.CONFIRM  # never automatic
    assert build_settings(replace(rec, audit_log=False)).safety.audit_log is False


def test_overrides_list_only_what_differs_from_defaults():
    assert minimal_overrides(build_settings(recommend(CPU_16, CATALOG))) == {
        "models": {"router": {"name": "gemma4:e2b", "num_ctx": 8192}}
    }
    assert minimal_overrides(Settings()) == {}


@pytest.mark.parametrize(
    "choices",
    [
        recommend(CPU_16, CATALOG),
        recommend(GPU_24, CATALOG),
        SetupChoices(
            main=tag("qwen3:8b"),
            router=None,
            embeddings=None,
            num_ctx=16384,
            keep_alive="2h",
            safety="strict",
            fast_path=False,
            direct_output=True,
            audit_log=False,
        ),
    ],
)
def test_written_config_loads_back_to_the_same_settings(tmp_path: Path, choices):
    path = tmp_path / "config.yaml"
    write_config(path, minimal_overrides(build_settings(choices)))
    assert load_settings(path, env={}) == build_settings(choices)


# -- wizard ------------------------------------------------------------------------------------


class ScriptedPrompter:
    """Answers wizard questions from a script; fails loudly if the wizard asks anything unexpected."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)
        self.said: list[str] = []
        self.warned: list[str] = []
        self.questions: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def warn(self, text: str) -> None:
        self.warned.append(text)

    def choose(self, question: str, options: Sequence[Option], default: int = 0) -> str:
        self.questions.append(question)
        answer = self._answers.pop(0)
        keys = [o.key for o in options]
        assert answer in keys, f"{answer!r} is not one of {keys} for {question!r}"
        return str(answer)

    def confirm(self, question: str, default: bool = True) -> bool:
        self.questions.append(question)
        answer = self._answers.pop(0)
        assert isinstance(answer, bool), (
            f"expected a yes/no answer for {question!r}, got {answer!r}"
        )
        return answer

    @property
    def finished(self) -> bool:
        return not self._answers


def test_default_mode_asks_only_for_final_confirmation():
    p = ScriptedPrompter(True)
    choices = run_wizard(p, CPU_16, CATALOG, mode="default")
    assert choices == recommend(CPU_16, CATALOG) and p.finished
    assert any("Recommended for this machine" in line for line in p.said)


def test_ask_mode_offers_default_or_advanced():
    p = ScriptedPrompter("default", True)
    assert run_wizard(p, CPU_16, CATALOG, mode="ask") == recommend(CPU_16, CATALOG)
    assert p.questions[0] == "How would you like to set up?"


def test_declining_the_review_cancels():
    assert run_wizard(ScriptedPrompter(False), CPU_16, CATALOG, mode="default") is None


def test_advanced_mode_applies_every_choice():
    p = ScriptedPrompter(
        "gemma4:e4b",  # main model (balanced; warns on this hardware but needs no confirmation)
        "granite4.1:3b",  # separate router
        "none",  # no embeddings
        "4096",  # context
        "5m",  # keep loaded
        "strict",  # approval rules
        False,  # fast path
        True,  # direct output
        False,  # command log
        True,  # save
    )
    choices = run_wizard(p, CPU_16, CATALOG, mode="advanced")
    assert p.finished
    assert choices == SetupChoices(
        main=tag("gemma4:e4b"),
        router=tag("granite4.1:3b"),
        embeddings=None,
        num_ctx=4096,
        keep_alive="5m",
        safety="strict",
        fast_path=False,
        direct_output=True,
        audit_log=False,
    )
    assert any(
        "Larger models use much more memory" in w for w in p.warned
    )  # up-front resource warning


def test_advanced_choosing_a_heavy_model_warns_and_requires_confirmation():
    p = ScriptedPrompter(
        "gpt-oss:20b",
        False,  # picks the heavy model, declines when warned
        "gemma4:e2b",  # picks again, accepted without confirmation
        "same",
        "nomic-embed-text",
        "8192",
        "30m",
        "default",
        True,
        False,
        True,
        True,
    )
    choices = run_wizard(p, CPU_16, CATALOG, mode="advanced")
    assert p.finished and choices.main.tag == "gemma4:e2b"
    warned = " ".join(p.warned)
    assert "large model" in warned and "swapping" in warned
    assert "Use GPT-OSS 20B anyway?" in p.questions


def test_advanced_can_still_choose_a_heavy_model_after_confirming():
    p = ScriptedPrompter(
        "gpt-oss:20b",
        True,
        "same",
        "none",
        "8192",
        "30m",
        "default",
        True,
        False,
        True,
        True,  # final: "serious warnings, save anyway?"
    )
    choices = run_wizard(p, CPU_16, CATALOG, mode="advanced")
    assert choices is not None and choices.main.tag == "gpt-oss:20b"
    assert "Save this configuration anyway?" in p.questions[-1]


def test_serious_warnings_can_cancel_at_the_review():
    p = ScriptedPrompter(
        "gpt-oss:20b", True, "same", "none", "8192", "30m", "default", True, False, True, False
    )
    assert run_wizard(p, CPU_16, CATALOG, mode="advanced") is None


def test_relaxed_safety_needs_explicit_confirmation():
    p = ScriptedPrompter(
        "gemma4:e2b",
        "same",
        "none",
        "8192",
        "30m",
        "relaxed",
        False,  # asked, then refused -> asked again
        "default",
        True,
        False,
        True,
        True,
    )
    choices = run_wizard(p, CPU_16, CATALOG, mode="advanced")
    assert choices.safety == "default"
    assert any("without asking" in w for w in p.warned)


def test_large_context_is_warned_about_immediately():
    p = ScriptedPrompter(
        "gemma4:e2b", "same", "none", "16384", "30m", "default", True, False, True, True
    )
    choices = run_wizard(p, CPU_16, CATALOG, mode="advanced")
    assert choices.num_ctx == 16384 and any("multiplies cache memory" in w for w in p.warned)


def test_model_menu_marks_recommendation_and_large_models():
    captured: dict[str, Sequence[Option]] = {}

    class Spy(ScriptedPrompter):
        def choose(self, question, options, default=0):
            captured.setdefault(question, options)
            return super().choose(question, options, default)

    p = Spy("gemma4:e2b", "same", "none", "8192", "30m", "default", True, False, True, True)
    run_wizard(p, CPU_16, CATALOG, mode="advanced")
    menu = {o.key: o for o in captured["Main model (chat, choosing tools, writing answers)"]}
    assert "recommended" in menu["gemma4:e2b"].label
    assert "large" in menu["gpt-oss:20b"].label and "may not fit" in menu["gpt-oss:20b"].label
    assert "download" in menu["gemma4:e4b"].detail and "GB" in menu["gemma4:e4b"].detail


# -- applying ----------------------------------------------------------------------------------


def test_write_config_merges_keeps_unrelated_keys_and_backs_up(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "packs:\n  disabled_tools: [kill_process]\nruntime:\n  max_steps: 5\n", encoding="utf-8"
    )
    backup = write_config(
        path, {"runtime": {"fast_path": False}, "models": {"main": {"name": "m:1"}}}
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["packs"] == {"disabled_tools": ["kill_process"]}
    assert data["runtime"] == {"max_steps": 5, "fast_path": False}
    assert data["models"]["main"]["name"] == "m:1"
    assert backup is not None and "max_steps: 5" in backup.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").startswith("# Written by the setup wizard")


def test_write_config_creates_missing_directories(tmp_path: Path):
    path = tmp_path / "a" / "b" / "config.yaml"
    assert write_config(path, {"runtime": {"fast_path": False}}) is None and path.exists()


def test_write_config_survives_a_malformed_existing_file(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    write_config(path, {"runtime": {"fast_path": False}})
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"runtime": {"fast_path": False}}


def test_needed_tags_are_unique_and_include_embeddings():
    assert needed_tags(build_settings(recommend(CPU_16, CATALOG))) == [
        "gemma4:e2b",
        "nomic-embed-text",
    ]
    split = build_settings(replace(recommend(CPU_16, CATALOG), router=tag("granite4.1:3b")))
    assert needed_tags(split) == ["granite4.1:3b", "gemma4:e2b", "nomic-embed-text"]
    no_embed = build_settings(replace(recommend(CPU_16, CATALOG), embeddings=None))
    assert needed_tags(no_embed) == ["gemma4:e2b"]


def test_missing_tags_understands_the_latest_suffix():
    installed = {"gemma4:e2b", "nomic-embed-text:latest"}
    assert missing_tags(["gemma4:e2b", "nomic-embed-text", "granite4.1:3b"], installed) == [
        "granite4.1:3b"
    ]


class FakeClient:
    def __init__(self, installed: Sequence[str] = ()) -> None:
        self._installed = installed
        self.pulled: list[str] = []

    def list(self) -> Any:
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self._installed])

    def pull(self, model: str, *, stream: bool) -> Any:
        self.pulled.append(model)
        yield SimpleNamespace(status="pulling manifest", total=None, completed=None)
        yield SimpleNamespace(status="downloading", total=100, completed=40)
        yield SimpleNamespace(status="success", total=100, completed=100)


def test_pull_reports_progress_and_installed_listing():
    client = FakeClient(["a:1", "b:2"])
    assert installed_tags(client) == {"a:1", "b:2"}
    seen: list[tuple[str, int | None, int | None]] = []
    pull_model(client, "x:1", lambda status, total, done: seen.append((status, total, done)))
    assert client.pulled == ["x:1"]
    assert seen == [
        ("pulling manifest", None, None),
        ("downloading", 100, 40),
        ("success", 100, 100),
    ]


def test_catalog_type_is_a_catalog():
    assert isinstance(CATALOG, Catalog)
