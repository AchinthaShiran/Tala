"""Build LangChain chat and embedding models from settings. New providers register here."""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from assistant.config import AgentSettings, EmbeddingSettings, ModelSettings
from assistant.domain import ConfigError

ChatBuilder = Callable[[ModelSettings, AgentSettings], BaseChatModel]
EmbeddingBuilder = Callable[[EmbeddingSettings], Embeddings]

# Model families that need asymmetric prefixes: name fragment -> (document, query).
_EMBEDDING_PREFIXES = {"nomic-embed-text": ("search_document: ", "search_query: ")}


class PrefixedEmbeddings(Embeddings):
    """Adds the document/query prefixes some embedding models were trained with."""

    def __init__(self, inner: Embeddings, doc_prefix: str, query_prefix: str) -> None:
        self._inner = inner
        self._doc_prefix = doc_prefix
        self._query_prefix = query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents([self._doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(self._query_prefix + text)


def _ollama_chat(model: ModelSettings, agent: AgentSettings) -> BaseChatModel:
    return ChatOllama(
        model=model.name,
        base_url=model.base_url,
        temperature=agent.temperature,
        num_ctx=model.num_ctx,
        num_predict=agent.max_tokens,
        keep_alive=model.keep_alive,
        reasoning=agent.think,  # explicit False stops thinking-capable models from reasoning
        client_kwargs={"timeout": model.request_timeout},
    )


def _ollama_embeddings(settings: EmbeddingSettings) -> Embeddings:
    inner: Embeddings = OllamaEmbeddings(model=settings.name, base_url=settings.base_url)
    for fragment, (doc, query) in _EMBEDDING_PREFIXES.items():
        if fragment in settings.name:
            return PrefixedEmbeddings(inner, doc, query)
    return inner


_CHAT_BUILDERS: dict[str, ChatBuilder] = {"ollama": _ollama_chat}
_EMBEDDING_BUILDERS: dict[str, EmbeddingBuilder] = {"ollama": _ollama_embeddings}


def register_provider(
    name: str, chat: ChatBuilder, embeddings: EmbeddingBuilder | None = None
) -> None:
    """Add a provider (e.g. an OpenAI-compatible server) without touching the agent code."""
    _CHAT_BUILDERS[name] = chat
    if embeddings is not None:
        _EMBEDDING_BUILDERS[name] = embeddings


def build_chat_model(model: ModelSettings, agent: AgentSettings) -> BaseChatModel:
    try:
        builder = _CHAT_BUILDERS[model.provider]
    except KeyError:
        raise ConfigError(f"unknown LLM provider '{model.provider}'") from None
    return builder(model, agent)


def build_embeddings(settings: EmbeddingSettings) -> Embeddings:
    try:
        builder = _EMBEDDING_BUILDERS[settings.provider]
    except KeyError:
        raise ConfigError(f"unknown embedding provider '{settings.provider}'") from None
    return builder(settings)
