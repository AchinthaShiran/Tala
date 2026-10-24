"""Composition root: the only place concrete classes are wired together."""

from __future__ import annotations

import platform as host
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from assistant.agent import AgentDeps, build_graph
from assistant.config import (
    AGENT_NAMES,
    AppPaths,
    Settings,
    TrustStore,
    builtin_packs_dir,
    project_packs_dir,
)
from assistant.domain import Platform, current_platform
from assistant.llm import build_chat_model, build_embeddings, warm_up
from assistant.memory import FactStore, open_checkpointer
from assistant.packs import LoadReport, PackRoot, ToolRegistry, load_packs
from assistant.retrieval import ToolIndex
from assistant.safety import AuditLog, JsonlAuditLog, NullAuditLog, PolicyEngine
from assistant.service import Assistant
from assistant.tools import CommandRunner, SubprocessRunner, ToolExecutor


@dataclass
class Runtime:
    """A fully wired assistant plus the pieces front ends and tooling want to inspect."""

    assistant: Assistant
    settings: Settings
    paths: AppPaths
    registry: ToolRegistry
    pack_report: LoadReport
    index: ToolIndex
    facts: FactStore
    warm: Callable[[], None] | None = None  # loads models; None when models are injected (tests)

    def start_warmup(self) -> None:
        """Load models in the background so the first request does not pay for it."""
        if self.warm is not None:
            threading.Thread(target=self.warm, name="model-warmup", daemon=True).start()

    def close(self) -> None:
        self.index.close()
        self.facts.close()


def untrusted_project_packs(paths: AppPaths, cwd: Path | None = None) -> Path | None:
    """The project pack directory that exists but is being ignored because it is not trusted."""
    directory = project_packs_dir(cwd)
    if directory.is_dir() and not TrustStore(paths.trusted_projects).is_trusted(cwd or Path.cwd()):
        return directory
    return None


def pack_roots(paths: AppPaths, settings: Settings, cwd: Path | None = None) -> list[PackRoot]:
    """Layers, lowest priority first: builtin < user < project (if trusted) < configured extras."""
    roots = [
        PackRoot(builtin_packs_dir(), "builtin"),
        PackRoot(paths.user_packs_dir, "user"),
    ]
    if untrusted_project_packs(paths, cwd) is None:
        roots.append(PackRoot(project_packs_dir(cwd), "project"))
    roots += [PackRoot(d.expanduser(), f"extra[{d.name}]") for d in settings.packs.dirs]
    return roots


def build_runtime(
    settings: Settings,
    paths: AppPaths,
    *,
    platform: Platform | None = None,
    chat_models: Mapping[str, BaseChatModel] | None = None,
    embeddings: Embeddings | None = None,
    runner: CommandRunner | None = None,
    checkpointer: BaseCheckpointSaver | None = None,  # type: ignore[type-arg]
    audit: AuditLog | None = None,
    which: Callable[[str], str | None] | None = None,
    cwd: Path | None = None,
) -> Runtime:
    """Wire everything. Every collaborator can be replaced, which is how tests run offline."""
    paths.ensure()
    target = platform or current_platform()

    report = load_packs(
        pack_roots(paths, settings, cwd),
        disabled_packs=settings.packs.disabled_packs,
        disabled_tools=settings.packs.disabled_tools,
    )
    registry = (
        ToolRegistry(report.tools.values(), target, which)
        if which
        else ToolRegistry(report.tools.values(), target)
    )

    if embeddings is None and settings.embeddings is not None and settings.retrieval.use_embeddings:
        embeddings = build_embeddings(settings.embeddings)
    index = ToolIndex(
        paths.index_db,
        settings.retrieval,
        embeddings,
        embedding_id=settings.embeddings.name if settings.embeddings else "",
    )
    index.sync(registry.available.values())

    models = (
        dict(chat_models)
        if chat_models
        else {
            name: build_chat_model(
                settings.models[settings.agents[name].model], settings.agents[name]
            )
            for name in AGENT_NAMES
        }
    )
    facts = FactStore(paths.facts_db)
    deps = AgentDeps(
        settings=settings,
        models=models,
        index=index,
        registry=registry,
        executor=ToolExecutor(registry, runner or SubprocessRunner()),
        policy=PolicyEngine(settings.safety),
        audit=audit
        or (JsonlAuditLog(paths.audit_log) if settings.safety.audit_log else NullAuditLog()),
        os_name=f"{host.system()} {host.release()}",
        facts=facts,
    )
    saver = checkpointer or open_checkpointer(paths.checkpoints_db)
    assistant = Assistant(build_graph(deps, saver), saver)
    warm = None if chat_models else (lambda: warm_up(settings))
    return Runtime(assistant, settings, paths, registry, report, index, facts, warm)
