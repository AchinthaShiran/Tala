"""ToolExecutor: validate, resolve and run a tool call; plus its LangChain adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool

from assistant.domain import ExecutionResult, ToolSpec
from assistant.domain.tool import ScalarValue
from assistant.packs import ToolRegistry
from assistant.tools.arguments import validate_arguments
from assistant.tools.rendering import format_command, render_arguments
from assistant.tools.runner import CommandRunner


@dataclass(frozen=True, slots=True)
class PreparedCall:
    """A validated call with its exact command line, ready to show and to run."""

    spec: ToolSpec
    arguments: dict[str, ScalarValue]
    argv: tuple[str, ...]

    @property
    def command(self) -> str:
        return format_command(list(self.argv))


class ToolExecutor:
    """Single path from (tool name, raw args) to a bounded command execution."""

    def __init__(self, registry: ToolRegistry, runner: CommandRunner) -> None:
        self._registry = registry
        self._runner = runner

    def prepare(self, name: str, raw_args: Mapping[str, Any]) -> PreparedCall:
        """Validate arguments and render argv. Raises AssistantError subclasses."""
        spec = self._registry.get(name)
        arguments = validate_arguments(spec, raw_args)
        executable = self._registry.resolve_executable(spec)
        rest = render_arguments(spec, arguments, self._registry.platform)
        return PreparedCall(spec, arguments, (executable, *rest))

    def execute(self, call: PreparedCall) -> ExecutionResult:
        return self._runner.run(
            call.argv,
            timeout=call.spec.timeout,
            max_bytes=call.spec.max_output_bytes,
            encoding=call.spec.output_encoding,
        )

    def to_langchain_tool(self, spec: ToolSpec) -> StructuredTool:
        """Expose a tool as a LangChain ``StructuredTool`` (content + ExecutionResult artifact)."""

        def _run(**kwargs: Any) -> tuple[str, ExecutionResult]:
            result = self.execute(self.prepare(spec.name, kwargs))
            return result.render(), result

        return StructuredTool(
            name=spec.name,
            description=spec.description,
            args_schema=spec.json_schema(),
            func=_run,
            response_format="content_and_artifact",
            metadata={"risk": spec.risk.value, "pack": spec.pack},
        )
