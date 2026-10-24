from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from assistant.bootstrap import Runtime, build_runtime
from assistant.config import AppPaths, Settings
from assistant.domain import Platform
from assistant.safety import AuditEntry
from tests.support import FakeRunner, ScriptedChatModel


class ListAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class Harness:
    """A fully wired offline assistant with scripted models."""

    def __init__(
        self,
        runtime: Runtime,
        models: dict[str, ScriptedChatModel],
        runner: FakeRunner,
        audit: ListAudit,
        saver: InMemorySaver,
    ) -> None:
        self.runtime = runtime
        self.assistant = runtime.assistant
        self.models = models
        self.runner = runner
        self.audit = audit
        self.saver = saver


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "config", tmp_path / "data")


@pytest.fixture
def make_harness(paths: AppPaths, tmp_path: Path) -> Callable[..., Harness]:
    def factory(
        scripts: dict[str, list[Any]] | None = None,
        *,
        settings: Settings | None = None,
        runner: FakeRunner | None = None,
    ) -> Harness:
        settings = settings or Settings(embeddings=None)
        scripts = scripts or {}
        models = {
            name: ScriptedChatModel(script=list(scripts.get(name, [])))
            for name in ("router", "chat", "executor", "summarizer")
        }
        runner = runner or FakeRunner("command output")
        audit, saver = ListAudit(), InMemorySaver()
        runtime = build_runtime(
            settings,
            paths,
            platform=Platform.LINUX,
            chat_models=models,
            runner=runner,
            checkpointer=saver,
            audit=audit,
            which=lambda exe: f"/fake/{exe}",
            cwd=tmp_path,
        )
        return Harness(runtime, models, runner, audit, saver)

    return factory
