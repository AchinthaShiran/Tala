"""Language-model construction and health checks."""

from assistant.llm.factory import (
    PrefixedEmbeddings,
    build_chat_model,
    build_embeddings,
    register_provider,
)
from assistant.llm.health import HealthCheck, check_backend
from assistant.llm.warmup import warm_up

__all__ = [
    "HealthCheck",
    "PrefixedEmbeddings",
    "build_chat_model",
    "build_embeddings",
    "check_backend",
    "register_provider",
    "warm_up",
]
