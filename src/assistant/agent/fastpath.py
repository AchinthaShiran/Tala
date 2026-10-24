"""Fast path: skip the executor model when retrieval alone is decisive and the call is trivial.

For a request like "how much disk space is left" the executor model spends seconds (on CPU, many
seconds) to emit a call with no arguments that retrieval had already identified. This module decides
when that is safe. It is deliberately conservative: only read-only tools that need no arguments, only
when the top hit is both a confident match and clearly ahead of the runner-up.
"""

from __future__ import annotations

from assistant.config import RetrievalSettings
from assistant.domain import RiskLevel
from assistant.packs import ToolRegistry
from assistant.retrieval import Confidence, SearchResult


def pick_fast_tool(
    result: SearchResult,
    registry: ToolRegistry,
    cfg: RetrievalSettings,
    *,
    margin: float,
) -> str | None:
    """Name of the tool to run without consulting the model, or ``None``."""
    if result.confidence is not Confidence.STRONG or not result.hits:
        return None
    top = result.hits[0]
    spec = registry.available.get(top.name)
    if spec is None or spec.risk is not RiskLevel.READ_ONLY or spec.required_params:
        return None
    runner_up = result.hits[1] if len(result.hits) > 1 else None

    if top.similarity is not None:
        if top.similarity < cfg.strong_similarity:
            return None
        close = (
            runner_up is not None
            and runner_up.similarity is not None
            and top.similarity - runner_up.similarity < margin
        )
        return None if close else top.name

    # Keyword-only mode: demand a name match, several matched terms, and a clear lead.
    if not top.name_match or top.matched_terms < 2:
        return None
    if runner_up is not None and runner_up.matched_terms >= top.matched_terms:
        return None
    return top.name
