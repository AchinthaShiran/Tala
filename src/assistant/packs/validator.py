"""Quality lint for tools that already satisfy the structural invariants of ``ToolSpec``."""

from __future__ import annotations

from assistant.domain import RiskLevel, ToolSpec
from assistant.packs.issues import PackIssue, Severity

MIN_EXAMPLES = 2


def lint_tool(spec: ToolSpec) -> list[PackIssue]:
    """Return warnings that improve retrieval quality and safety review."""
    issues: list[PackIssue] = []

    def warn(message: str) -> None:
        issues.append(PackIssue(Severity.WARNING, message, spec.source, spec.name))

    if not spec.examples:
        issues.append(
            PackIssue(
                Severity.ERROR, "at least one example query is required", spec.source, spec.name
            )
        )
    elif len(spec.examples) < MIN_EXAMPLES:
        warn(f"add at least {MIN_EXAMPLES} example queries to improve tool selection")
    for name, param in spec.parameters.items():
        if not param.description:
            warn(f"parameter '{name}' has no description; the model relies on it")
        if (
            param.type == "string"
            and param.pattern is None
            and param.enum is None
            and param.max_length is None
        ):
            warn(f"string parameter '{name}' has no pattern/enum/max_length constraint")
    if spec.risk is not RiskLevel.READ_ONLY and not spec.confirm_message:
        issues.append(
            PackIssue(
                Severity.INFO,
                "mutating tool without confirm_message; the command line is still shown",
                spec.source,
                spec.name,
            )
        )
    return issues
