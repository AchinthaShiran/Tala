"""Load models into memory ahead of the first request.

The first call to a cold model pays for loading it (seconds on CPU, more on large models). Doing it in
the background while the user is still typing removes that from time-to-first-token. The warm-up
requests the same ``num_ctx``/``keep_alive`` the agents use, because Ollama reloads a model whose
context size differs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import ollama

from assistant.config import ModelSettings, Settings

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120.0
# The router model is only needed for ambiguous requests, so it is not preloaded.
_WARM_AGENTS = ("chat", "executor", "summarizer")


def warm_up(settings: Settings) -> None:
    """Best-effort and silent: never raises, never blocks the caller if run in a thread."""
    embeddings = settings.embeddings
    if embeddings is not None and settings.retrieval.use_embeddings:
        _attempt(
            "embeddings",
            lambda: ollama.Client(host=embeddings.base_url, timeout=_TIMEOUT_SECONDS).embed(
                model=embeddings.name, input="warm up"
            ),
        )

    loaded: set[tuple[str, str, int]] = set()
    for agent in _WARM_AGENTS:
        model = settings.models[settings.agents[agent].model]
        key = (model.base_url, model.name, model.num_ctx)
        if model.provider != "ollama" or key in loaded:
            continue
        loaded.add(key)
        _attempt(f"model {model.name}", _loader(model))


def _loader(model: ModelSettings) -> Callable[[], object]:
    """An action that loads ``model`` without generating anything (empty prompt)."""

    def load() -> object:
        client = ollama.Client(host=model.base_url, timeout=_TIMEOUT_SECONDS)
        return client.generate(
            model=model.name,
            prompt="",
            keep_alive=model.keep_alive or "5m",
            options={"num_ctx": model.num_ctx},
        )

    return load


def _attempt(what: str, action: Callable[[], object]) -> None:
    try:
        action()
    except Exception as exc:
        log.debug("warm-up of %s failed: %s", what, exc)
