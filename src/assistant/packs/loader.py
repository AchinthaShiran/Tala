"""Load tool packs from layered directories, reporting every problem instead of hiding it."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from assistant.domain import ToolSpec
from assistant.packs.issues import PackIssue, Severity
from assistant.packs.validator import lint_tool


@dataclass(frozen=True, slots=True)
class PackRoot:
    """A directory of pack files. Later roots override earlier ones."""

    path: Path
    label: str


class _PackFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack: str
    version: str = "0.0.0"
    description: str = ""
    tools: list[dict[str, Any]]


@dataclass
class LoadReport:
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    issues: list[PackIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[PackIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[PackIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]


def load_packs(
    roots: Sequence[PackRoot],
    *,
    disabled_packs: Iterable[str] = (),
    disabled_tools: Iterable[str] = (),
) -> LoadReport:
    """Load every ``*.yaml``/``*.yml`` under each root. Never raises on bad content."""
    report = LoadReport()
    off_packs, off_tools = set(disabled_packs), set(disabled_tools)
    for root in roots:
        seen_in_root: dict[str, str] = {}
        for file in _pack_files(root.path):
            _load_file(file, root, report, seen_in_root, off_packs, off_tools)
    return report


def _pack_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted([*directory.rglob("*.yaml"), *directory.rglob("*.yml")])


def _load_file(
    file: Path,
    root: PackRoot,
    report: LoadReport,
    seen_in_root: dict[str, str],
    off_packs: set[str],
    off_tools: set[str],
) -> None:
    label = f"{root.label}:{file.name}"

    def issue(sev: Severity, msg: str, tool: str | None = None) -> None:
        report.issues.append(PackIssue(sev, msg, label, tool))

    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        pack_file = _PackFile.model_validate(raw)
    except (OSError, yaml.YAMLError) as exc:
        issue(Severity.ERROR, f"cannot read pack: {exc}")
        return
    except ValidationError as exc:
        issue(Severity.ERROR, f"invalid pack file: {_summarise(exc)}")
        return

    if pack_file.pack in off_packs:
        issue(Severity.INFO, f"pack '{pack_file.pack}' disabled by configuration")
        return

    for raw_tool in pack_file.tools:
        name = str(raw_tool.get("name", "<unnamed>"))
        if name in off_tools:
            issue(Severity.INFO, "disabled by configuration", name)
            continue
        try:
            spec = ToolSpec.model_validate({**raw_tool, "pack": pack_file.pack, "source": label})
        except ValidationError as exc:
            issue(Severity.ERROR, _summarise(exc), name)
            continue
        if spec.name in seen_in_root:
            issue(
                Severity.ERROR,
                f"duplicate tool name (first defined in {seen_in_root[spec.name]})",
                name,
            )
            continue
        seen_in_root[spec.name] = label
        lint = lint_tool(spec)
        report.issues.extend(lint)
        if any(i.severity is Severity.ERROR for i in lint):
            continue
        if spec.name in report.tools:
            issue(Severity.INFO, f"overrides tool from {report.tools[spec.name].source}", name)
        report.tools[spec.name] = spec


def _summarise(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)
