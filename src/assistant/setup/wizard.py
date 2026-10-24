"""The setup wizard's flow. Talks to the user only through a ``Prompter`` so it can be tested."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from assistant.setup.catalog import Catalog, ModelEntry
from assistant.setup.choices import SAFETY_PROFILES, SetupChoices
from assistant.setup.hardware import Hardware
from assistant.setup.planner import (
    DANGER_FRACTION,
    Advice,
    assess,
    baseline,
    estimate_memory_gb,
    model_memory_gb,
    recommend,
)

Mode = Literal["ask", "default", "recommended", "advanced"]

TITLES = {
    "default": "Default setup",
    "recommended": "Recommended setup",
    "advanced": "Advanced setup",
}

CONTEXT_SIZES = (4096, 8192, 16384, 32768)
KEEP_ALIVE_OPTIONS = (
    ("5m", "5 minutes", "Frees memory soonest; the first request after a pause is slower."),
    ("30m", "30 minutes", "Default."),
    ("2h", "2 hours", "Holds memory while you are idle."),
    ("-1", "Until Ollama stops", "Always loaded. Fastest, but holds memory permanently."),
)


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    label: str
    detail: str = ""


class Prompter(Protocol):
    def say(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def choose(self, question: str, options: Sequence[Option], default: int = 0) -> str: ...
    def confirm(self, question: str, default: bool = True) -> bool: ...


def run_wizard(
    prompter: Prompter, hw: Hardware, catalog: Catalog, *, mode: Mode = "ask"
) -> SetupChoices | None:
    """Return the confirmed choices, or ``None`` if the user backs out.

    Whatever the mode, the full settings are shown and must be accepted before anything is applied.
    """
    base = baseline(catalog)
    recommended = recommend(hw, catalog)
    prompter.say(f"Detected: {hw.describe()}")
    prompter.say(_recommendation_line(hw, recommended))

    chosen: str = mode
    while True:
        if mode == "ask":
            chosen = _pick_mode(prompter, base, recommended)
        if chosen == "default":
            choices = base
        elif chosen == "recommended":
            choices = recommended
        else:
            choices = _advanced(prompter, hw, catalog, recommended)
        if _review(prompter, hw, choices, TITLES[chosen]):
            return choices
        if mode != "ask" or not prompter.confirm("Choose a different setup?", default=True):
            return None


def _recommendation_line(hw: Hardware, rec: SetupChoices) -> str:
    reason = (
        "your GPU has room for it"
        if hw.vram_gb is not None
        else "no supported GPU was detected, so the lighter models keep answers quick"
        if not hw.accelerated
        else "your memory has room for it"
    )
    return f"Recommended for this machine: {rec.main.label} ({reason})."


def _compact(c: SetupChoices) -> str:
    """One line with the values that matter, so each option can be judged before it is picked."""
    router = "the main model also routes" if c.router is None else f"{c.router.label} routes"
    embeddings = c.embeddings.label if c.embeddings else "keyword search"
    return (
        f"{c.main.label}; {router}; {embeddings}; {c.num_ctx} tokens; "
        f"keep loaded {c.keep_alive}; about {estimate_memory_gb(c):.1f} GB"
    )


def _pick_mode(p: Prompter, base: SetupChoices, rec: SetupChoices) -> str:
    same = " (same as the default setup)" if rec == base else ""
    return p.choose(
        "How would you like to set up? You will see the full settings and confirm before "
        "anything is applied.",
        [
            Option(
                "default",
                "Default setup",
                f"The same on every machine: {_compact(base)}.",
            ),
            Option(
                "recommended",
                f"Recommended for this machine{same}",
                f"Tailored to the detected hardware: {_compact(rec)}.",
            ),
            Option(
                "advanced",
                "Advanced setup",
                "Choose models, context size, memory use, approval rules and speed options yourself.",
            ),
        ],
        default=1,
    )


# -- advanced ----------------------------------------------------------------------------------


def _advanced(p: Prompter, hw: Hardware, catalog: Catalog, rec: SetupChoices) -> SetupChoices:
    p.say("Advanced setup: press Enter to accept the recommended option at each step.")
    p.warn("Larger models use much more memory and can slow everything else on this computer.")
    choices = _ask_main(p, hw, catalog, rec, rec)
    choices = replace(choices, router=_ask_router(p, catalog, choices, rec))
    choices = replace(choices, embeddings=_ask_embeddings(p, catalog, rec))
    choices = replace(choices, num_ctx=_ask_context(p, choices, rec))
    choices = replace(choices, keep_alive=_ask_keep_alive(p, rec))
    choices = replace(choices, safety=_ask_safety(p, rec))
    choices = replace(
        choices,
        fast_path=p.confirm(
            "Skip the model for simple, safe requests such as 'how much disk space is left' (faster)?",
            default=True,
        ),
        direct_output=p.confirm(
            "Show small command results as-is instead of a written summary (fastest first output)?",
            default=False,
        ),
        audit_log=p.confirm("Keep a log of every command it runs?", default=True),
    )
    return choices


def _model_option(
    m: ModelEntry, hw: Hardware, num_ctx: int, recommended: ModelEntry | None
) -> Option:
    needs = model_memory_gb(m, num_ctx)
    budget = hw.budget_gb
    flags = []
    if recommended is not None and m.tag == recommended.tag:
        flags.append("recommended")
    if m.tier == "heavy":
        flags.append("⚠ large")
    if budget is not None and needs > budget * DANGER_FRACTION:
        flags.append("⚠ may not fit in memory")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    detail = f"{m.tier} · download {m.download_gb:.1f} GB · needs about {needs:.1f} GB. {m.notes}"
    return Option(m.tag, f"{m.label} ({m.tag}){suffix}", detail)


def _default_index(options: Sequence[Option], key: str | None) -> int:
    return next((i for i, o in enumerate(options) if o.key == key), 0)


def _ask_main(
    p: Prompter, hw: Hardware, catalog: Catalog, choices: SetupChoices, rec: SetupChoices
) -> SetupChoices:
    models = catalog.chat_models()
    options = [_model_option(m, hw, choices.num_ctx, rec.main) for m in models]
    while True:
        key = p.choose(
            "Main model (chat, choosing tools, writing answers)",
            options,
            default=_default_index(options, rec.main.tag),
        )
        model = catalog.get(key)
        assert model is not None
        trial = replace(choices, main=model)
        serious = [a for a in assess(trial, hw) if a.level in ("warn", "danger")]
        for advice in serious:
            p.warn(advice.text)
        needs_confirmation = model.tier == "heavy" or any(a.level == "danger" for a in serious)
        if not needs_confirmation or p.confirm(f"Use {model.label} anyway?", default=False):
            return trial


def _ask_router(
    p: Prompter, catalog: Catalog, choices: SetupChoices, rec: SetupChoices
) -> ModelEntry | None:
    options = [
        Option(
            "same",
            "Use the main model for routing",
            "No extra model in memory. Routing is a tiny task, so this costs little.",
        )
    ]
    for m in catalog.router_models():
        options.append(
            Option(
                m.tag,
                f"{m.label} ({m.tag})",
                f"Separate small model, about {m.memory_gb:.1f} GB more memory.",
            )
        )
    key = p.choose(
        "Routing model (decides whether a message needs a tool)",
        options,
        default=_default_index(options, rec.router.tag if rec.router else "same"),
    )
    return None if key == "same" else catalog.get(key)


def _ask_embeddings(p: Prompter, catalog: Catalog, rec: SetupChoices) -> ModelEntry | None:
    options = [
        Option(
            "none",
            "No embeddings (keyword search only)",
            "Nothing extra to download or load; tool matching is a little less accurate.",
        )
    ]
    for m in catalog.embedding_models():
        options.append(
            Option(
                m.tag,
                f"{m.label} ({m.tag})",
                f"download {m.download_gb:.2f} GB · {m.notes}",
            )
        )
    key = p.choose(
        "Embedding model (helps find the right tool for a request)",
        options,
        default=_default_index(options, rec.embeddings.tag if rec.embeddings else "none"),
    )
    return None if key == "none" else catalog.get(key)


def _ask_context(p: Prompter, choices: SetupChoices, rec: SetupChoices) -> int:
    options = [
        Option(
            str(size),
            f"{size} tokens",
            f"Total memory for the chosen models: about "
            f"{estimate_memory_gb(replace(choices, num_ctx=size)):.1f} GB."
            + (" Plenty for tool requests." if size == 8192 else ""),
        )
        for size in CONTEXT_SIZES
    ]
    key = p.choose(
        "Context size (how much conversation the model can see)",
        options,
        default=_default_index(options, str(rec.num_ctx)),
    )
    size = int(key)
    if size >= 16384:
        p.warn("A larger context multiplies cache memory and slows every request.")
    return size


def _ask_keep_alive(p: Prompter, rec: SetupChoices) -> str:
    options = [Option(key, label, detail) for key, label, detail in KEEP_ALIVE_OPTIONS]
    return p.choose(
        "How long should models stay loaded after use?",
        options,
        default=_default_index(options, rec.keep_alive),
    )


def _ask_safety(p: Prompter, rec: SetupChoices) -> str:
    options = [Option(s.key, s.label, s.detail) for s in SAFETY_PROFILES]
    while True:
        key = p.choose(
            "Approval rules (when does it ask before running a command?)",
            options,
            default=_default_index(options, rec.safety),
        )
        if key != "relaxed":
            return key
        p.warn("Relaxed rules let a wrong or manipulated model change your system without asking.")
        if p.confirm("Use relaxed rules anyway?", default=False):
            return key


# -- review ------------------------------------------------------------------------------------


def summary_lines(choices: SetupChoices) -> list[str]:
    router = choices.router.label if choices.router else "same as main model"
    embeddings = choices.embeddings.label if choices.embeddings else "none (keyword search)"
    profile = next(s for s in SAFETY_PROFILES if s.key == choices.safety)
    return [
        f"Main model:        {choices.main.label} ({choices.main.tag})",
        f"Routing model:     {router}",
        f"Embeddings:        {embeddings}",
        f"Context size:      {choices.num_ctx} tokens",
        f"Keep loaded:       {choices.keep_alive}",
        f"Approval rules:    {profile.key}",
        f"Fast path:         {'on' if choices.fast_path else 'off'}",
        f"Direct output:     {'on' if choices.direct_output else 'off'}",
        f"Command log:       {'on' if choices.audit_log else 'off'}",
        f"Estimated memory:  about {estimate_memory_gb(choices):.1f} GB with everything loaded",
    ]


def _review(p: Prompter, hw: Hardware, choices: SetupChoices, title: str) -> bool:
    p.say(f"{title}: these settings will be applied.")
    for line in summary_lines(choices):
        p.say("  " + line)
    advice: list[Advice] = assess(choices, hw)
    for item in advice:
        (p.warn if item.level in ("warn", "danger") else p.say)(item.text)
    if any(a.level == "danger" for a in advice):
        return p.confirm("There are serious warnings above. Save this configuration anyway?", False)
    return p.confirm("Save this configuration?", True)
