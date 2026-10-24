"""Recommendations, memory estimates and resource warnings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from assistant.setup.catalog import Catalog, ModelEntry, Tier
from assistant.setup.choices import ROUTER_CTX, SetupChoices
from assistant.setup.hardware import Hardware

WARN_FRACTION = 0.6  # of the usable budget: noticeably squeezes other applications
DANGER_FRACTION = 0.9  # of the usable budget: likely to swap, stall or fail to load
LARGE_CTX = 16384
LONG_KEEP_ALIVE = {"2h", "-1"}
CPU_SLOW_WEIGHTS_GB = 5.0
ROUTER_MIN_BUDGET_GB = 16.0
LOW_RAM_GB = 12.0  # below this, free memory sooner by unloading idle models
DEFAULT_MAIN_TAG = "gemma4:e2b"
DEFAULT_EMBEDDING_TAG = "nomic-embed-text"
DEFAULT_KEEP_ALIVE = "5m"


@dataclass(frozen=True, slots=True)
class Advice:
    level: Literal["info", "warn", "danger"]
    text: str


def recommend_tier(hw: Hardware) -> Tier:
    """Light unless there is real acceleration: on CPU even small models answer in seconds."""
    budget = hw.budget_gb
    if budget is None or not hw.accelerated:
        return "light"
    if budget >= 24:
        return "heavy"
    if budget >= 10:
        return "balanced"
    return "light"


def baseline(catalog: Catalog) -> SetupChoices:
    """The Default setup: one fixed, conservative configuration that is the same on every machine."""
    main, embeddings = catalog.get(DEFAULT_MAIN_TAG), catalog.get(DEFAULT_EMBEDDING_TAG)
    if main is None or embeddings is None:
        raise ValueError("the catalog must contain the default main and embedding models")
    return SetupChoices(
        main=main,
        router=None,
        embeddings=embeddings,
        num_ctx=8192,
        keep_alive=DEFAULT_KEEP_ALIVE,
    )


def recommend(hw: Hardware, catalog: Catalog) -> SetupChoices:
    """The Recommended setup: tailored to the detected hardware."""
    tier = recommend_tier(hw)
    low_memory = hw.ram_gb is not None and hw.ram_gb < 8
    budget = hw.budget_gb
    # A dedicated router only pays off with real acceleration; it is consulted rarely, and on a
    # CPU an extra resident model just costs memory.
    roomy = hw.accelerated and budget is not None and budget >= ROUTER_MIN_BUDGET_GB
    return SetupChoices(
        main=catalog.default_for("chat", tier),
        router=catalog.get("granite4.1:3b") if roomy else None,
        embeddings=catalog.default_for("embedding", "light"),
        num_ctx=4096 if low_memory else 8192,
        keep_alive="5m" if hw.ram_gb is not None and hw.ram_gb < LOW_RAM_GB else "30m",
    )


def estimate_memory_gb(choices: SetupChoices) -> float:
    """Approximate resident memory with the chosen models loaded together."""
    total = choices.main.memory_gb + choices.main.kv_gb_per_8k * choices.num_ctx / 8192
    router = choices.router
    if router is not None and router.tag != choices.main.tag:
        total += router.memory_gb + router.kv_gb_per_8k * ROUTER_CTX / 8192
    if choices.embeddings is not None:
        total += choices.embeddings.memory_gb
    return round(total, 1)


def model_memory_gb(model: ModelEntry, num_ctx: int) -> float:
    return round(model.memory_gb + model.kv_gb_per_8k * num_ctx / 8192, 1)


def assess(choices: SetupChoices, hw: Hardware) -> list[Advice]:
    """Everything the user should know before committing to these choices."""
    advice: list[Advice] = []
    main = choices.main
    needed = estimate_memory_gb(choices)
    budget = hw.budget_gb

    if budget is not None:
        share = needed / budget
        where = "GPU memory" if hw.vram_gb is not None else "memory"
        if share > DANGER_FRACTION:
            advice.append(
                Advice(
                    "danger",
                    f"These models need about {needed:.1f} GB but only about {budget:.0f} GB of "
                    f"{where} is usable. Expect heavy swapping, freezes, or the model failing to load.",
                )
            )
        elif share > WARN_FRACTION:
            advice.append(
                Advice(
                    "warn",
                    f"These models need about {needed:.1f} GB of roughly {budget:.0f} GB usable "
                    f"{where}. Other applications will feel slower while the assistant is loaded.",
                )
            )
    if main.tier == "heavy":
        advice.append(
            Advice(
                "warn",
                f"{main.label} is a large model: it takes a long time to download and load, uses a "
                "lot of memory, and answers much more slowly without a powerful GPU.",
            )
        )
    elif main.tier == "balanced" and not hw.accelerated:
        advice.append(
            Advice(
                "warn",
                f"{main.label} is larger than the default and no GPU was detected, so every "
                "answer will be noticeably slower than with the light models.",
            )
        )
    if not hw.accelerated and main.memory_gb > CPU_SLOW_WEIGHTS_GB and main.tier == "light":
        advice.append(
            Advice("info", "No GPU detected: answers run on the CPU and take several seconds.")
        )
    if not main.tool_calling:
        advice.append(
            Advice("danger", f"{main.label} does not support tool calling, so it cannot run tools.")
        )
    if choices.num_ctx >= LARGE_CTX:
        advice.append(
            Advice(
                "warn",
                f"A context of {choices.num_ctx} tokens multiplies cache memory and slows every "
                "request. Most tool requests fit comfortably in 8192.",
            )
        )
    if choices.keep_alive in LONG_KEEP_ALIVE:
        advice.append(
            Advice("warn", "Models stay in memory while you are idle, holding those resources.")
        )
    if choices.router is not None and choices.router.tag != main.tag:
        advice.append(
            Advice("info", f"A separate router model ({choices.router.label}) stays loaded too.")
        )
    if choices.embeddings is None:
        advice.append(
            Advice(
                "info", "Without embeddings, tool search is keyword-only: a little less accurate."
            )
        )
    if choices.safety == "relaxed":
        advice.append(
            Advice(
                "danger",
                "Relaxed safety lets the model change your system without asking. Only use it on a "
                "machine you can afford to break.",
            )
        )
    if choices.safety == "strict":
        advice.append(
            Advice("info", "Strict safety prompts before every tool, including harmless reads.")
        )
    return advice


def with_main(choices: SetupChoices, model: ModelEntry) -> SetupChoices:
    return replace(choices, main=model)
