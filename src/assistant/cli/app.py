"""`lpa` command line: a thin shell over the service API (no business logic here)."""

from __future__ import annotations

import json
import platform as host
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from assistant import __version__
from assistant.bootstrap import Runtime, build_runtime, pack_roots
from assistant.cli.render import ConsoleRenderer
from assistant.config import AppPaths, Settings, TrustStore, default_paths, load_settings
from assistant.domain import AssistantError, current_platform
from assistant.evaluation import (
    SimulatedRunner,
    evaluate_agent,
    evaluate_retrieval,
    load_cases,
    registry_for_retrieval_eval,
)
from assistant.llm import build_embeddings, check_backend
from assistant.memory import FactStore
from assistant.packs import PackRoot, Severity, ToolRegistry, load_packs
from assistant.retrieval import ToolIndex

app = typer.Typer(
    help="Local PC assistant: chat in natural language, extend it with YAML packs.",
    no_args_is_help=True,
    add_completion=False,
)
packs_app = typer.Typer(help="Inspect and validate tool packs.", no_args_is_help=True)
facts_app = typer.Typer(help="Long-term facts the assistant should remember.", no_args_is_help=True)
app.add_typer(packs_app, name="packs")
app.add_typer(facts_app, name="facts")
eval_app = typer.Typer(
    help="Measure tool-selection quality on the golden set.", no_args_is_help=True
)
app.add_typer(eval_app, name="eval")

console = Console()
ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to a config.yaml")]


def _load(config: Path | None) -> tuple[Settings, AppPaths]:
    settings = load_settings(config or default_paths().config_file)
    return settings, default_paths(settings.data_dir)


def create_runtime(config: Path | None) -> Runtime:
    """Overridable in tests."""
    settings, paths = _load(config)
    return build_runtime(settings, paths)


def _fail(message: str) -> typer.Exit:
    console.print(f"[bold red]Error:[/bold red] {message}")
    return typer.Exit(code=1)


# -- chat ------------------------------------------------------------------------------------


@app.command()
def chat(
    session: Annotated[
        str, typer.Option("--session", "-s", help="Session name (resumable)")
    ] = "default",
    config: ConfigOpt = None,
    show_output: Annotated[
        bool, typer.Option("--show-output", help="Always print raw tool output")
    ] = False,
) -> None:
    """Interactive chat. Commands: /tools /reset /history /exit"""
    try:
        runtime = create_runtime(config)
    except AssistantError as exc:
        raise _fail(str(exc)) from exc
    renderer = ConsoleRenderer(console, show_tool_output=show_output)
    assistant = runtime.assistant
    console.print(
        f"[bold]Local Assistant {__version__}[/bold] · {len(runtime.registry)} tools on "
        f"{current_platform().value} · session '{session}' · /help for commands"
    )
    try:
        while True:
            try:
                text = console.input("[bold cyan]You:[/bold cyan] ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.startswith("/"):
                if _slash(text, runtime, session):
                    break
                continue
            try:
                _turn(renderer, assistant.send(session, text), assistant, session)
            except KeyboardInterrupt:
                console.print("\n[dim](interrupted)[/dim]")
    except KeyboardInterrupt:
        console.print()
    finally:
        runtime.close()


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="What to ask or do")],
    session: Annotated[str, typer.Option("--session", "-s")] = "oneshot",
    config: ConfigOpt = None,
    show_output: Annotated[bool, typer.Option("--show-output")] = False,
) -> None:
    """Ask a single question and exit."""
    try:
        runtime = create_runtime(config)
    except AssistantError as exc:
        raise _fail(str(exc)) from exc
    try:
        renderer = ConsoleRenderer(console, show_tool_output=show_output)
        _turn(renderer, runtime.assistant.send(session, question), runtime.assistant, session)
    finally:
        runtime.close()


def _turn(renderer: ConsoleRenderer, events, assistant, session: str) -> None:  # type: ignore[no-untyped-def]
    renderer.begin_turn()
    pending = renderer.run_events(events)
    while pending is not None:
        decisions = renderer.ask_approvals(pending)
        renderer.begin_turn()
        pending = renderer.run_events(assistant.resume(session, decisions))


def _slash(command: str, runtime: Runtime, session: str) -> bool:
    """Handle a REPL command; returns True to exit."""
    name = command.split()[0].lower()
    if name in {"/exit", "/quit"}:
        return True
    if name == "/reset":
        runtime.assistant.reset(session)
        console.print("[dim]Session cleared.[/dim]")
    elif name == "/history":
        for turn in runtime.assistant.history(session):
            who = "You" if turn.role == "user" else "Assistant"
            console.print(f"[bold]{who}:[/bold] {escape(turn.text)}")
    elif name == "/tools":
        _print_tools(runtime.registry, show_unavailable=False)
    else:
        console.print("Commands: /tools /history /reset /exit")
    return False


# -- packs -----------------------------------------------------------------------------------


def _print_tools(registry: ToolRegistry, *, show_unavailable: bool) -> None:
    table = Table("tool", "risk", "pack", "description")
    for spec in sorted(registry.available.values(), key=lambda s: (s.pack, s.name)):
        table.add_row(spec.name, spec.risk.value, spec.pack, escape(spec.description))
    console.print(table)
    if show_unavailable:
        missing = Table("tool", "why unavailable")
        for name, item in sorted(registry.unavailable.items()):
            missing.add_row(name, item.reason)
        console.print(missing)


@packs_app.command("list")
def packs_list(
    config: ConfigOpt = None,
    all_tools: Annotated[bool, typer.Option("--all", help="Also show unavailable tools")] = False,
) -> None:
    """List tools available on this machine."""
    settings, paths = _load(config)
    report = load_packs(
        pack_roots(paths, settings),
        disabled_packs=settings.packs.disabled_packs,
        disabled_tools=settings.packs.disabled_tools,
    )
    registry = ToolRegistry(report.tools.values(), current_platform())
    _print_tools(registry, show_unavailable=all_tools)
    console.print(
        f"{len(registry)} available, {len(registry.unavailable)} unavailable, "
        f"{len(report.errors)} pack errors"
    )


@packs_app.command("show")
def packs_show(name: str, config: ConfigOpt = None) -> None:
    """Show one tool's full definition."""
    settings, paths = _load(config)
    report = load_packs(pack_roots(paths, settings))
    spec = report.tools.get(name)
    if spec is None:
        raise _fail(f"no tool named '{name}'")
    console.print_json(json.dumps(spec.model_dump(mode="json", exclude_none=True)))


@packs_app.command("trust")
def packs_trust(
    project: Annotated[
        Path | None, typer.Argument(help="Project directory (default: here)")
    ] = None,
    revoke: Annotated[bool, typer.Option("--revoke", help="Stop trusting it")] = False,
    config: ConfigOpt = None,
) -> None:
    """Allow (or stop allowing) packs from <project>/.assistant/packs to load."""
    _, paths = _load(config)
    directory = (project or Path.cwd()).resolve()
    store = TrustStore(paths.trusted_projects)
    if revoke:
        console.print("Revoked." if store.revoke(directory) else "It was not trusted.")
        return
    packs_dir = directory / ".assistant" / "packs"
    if packs_dir.is_dir():
        console.print("Packs that will be able to run commands on this machine:")
        for file in sorted(packs_dir.rglob("*.y*ml")):
            console.print(f"  {file.relative_to(directory)}")
    store.trust(directory)
    console.print(f"Trusted [bold]{directory}[/bold]. Review its packs; they define what can run.")


@packs_app.command("validate")
def packs_validate(
    paths: Annotated[list[Path] | None, typer.Argument(help="Pack files or directories")] = None,
    config: ConfigOpt = None,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as errors")] = False,
) -> None:
    """Lint packs. Exit code 1 when there are errors (or warnings with --strict)."""
    if paths:
        roots = [PackRoot(p if p.is_dir() else p.parent, p.name) for p in paths]
        if any(not p.exists() for p in paths):
            raise _fail("path does not exist")
    else:
        settings, app_paths = _load(config)
        roots = pack_roots(app_paths, settings)
    report = load_packs(roots)
    for issue in report.issues:
        if issue.severity is Severity.INFO:
            continue
        style = "red" if issue.severity is Severity.ERROR else "yellow"
        console.print(f"[{style}]{issue}[/{style}]")
    console.print(
        f"{len(report.tools)} tools loaded, {len(report.errors)} errors, {len(report.warnings)} warnings"
    )
    if report.errors or (strict and report.warnings):
        raise typer.Exit(code=1)


# -- doctor ----------------------------------------------------------------------------------


@app.command()
def doctor(config: ConfigOpt = None) -> None:
    """Diagnose configuration, packs and the language-model backend."""
    settings, paths = _load(config)
    table = Table("check", "status", "detail")
    failed = False

    def row(name: str, ok: bool, detail: str, fatal: bool = True) -> None:
        nonlocal failed
        failed = failed or (not ok and fatal)
        mark = (
            "[green]ok[/green]" if ok else ("[red]FAIL[/red]" if fatal else "[yellow]warn[/yellow]")
        )
        table.add_row(name, mark, detail)

    row(
        "platform",
        True,
        f"{host.system()} {host.release()} ({current_platform().value}), Python {sys.version.split()[0]}",
    )
    row(
        "config",
        True,
        str(paths.config_file) + ("" if paths.config_file.exists() else " (defaults)"),
    )
    report = load_packs(
        pack_roots(paths, settings),
        disabled_packs=settings.packs.disabled_packs,
        disabled_tools=settings.packs.disabled_tools,
    )
    registry = ToolRegistry(report.tools.values(), current_platform())
    row(
        "packs",
        not report.errors,
        f"{len(report.tools)} tools, {len(report.errors)} errors, {len(report.warnings)} warnings",
    )
    row(
        "tools available",
        len(registry) > 0,
        f"{len(registry)} runnable, {len(registry.unavailable)} unavailable here",
        fatal=False,
    )
    for check in check_backend(settings):
        row(check.name, check.ok, check.detail, check.fatal)
    console.print(table)
    if failed:
        raise typer.Exit(code=1)


# -- facts / audit / sessions ------------------------------------------------------------------


def _facts(config: Path | None) -> FactStore:
    _, paths = _load(config)
    paths.ensure()
    return FactStore(paths.facts_db)


@facts_app.command("add")
def facts_add(key: str, value: str, config: ConfigOpt = None) -> None:
    """Remember a fact, e.g. `lpa facts add "phone ip" 192.168.1.20:5555`."""
    store = _facts(config)
    try:
        store.remember(key, value)
    except ValueError as exc:
        raise _fail(str(exc)) from exc
    console.print(f"Remembered [bold]{key}[/bold].")


@facts_app.command("list")
def facts_list(config: ConfigOpt = None) -> None:
    for key, value in _facts(config).all().items():
        console.print(f"[bold]{key}[/bold]: {value}")


@facts_app.command("remove")
def facts_remove(key: str, config: ConfigOpt = None) -> None:
    if not _facts(config).forget(key):
        raise _fail(f"no fact named '{key}'")
    console.print(f"Forgot [bold]{key}[/bold].")


@app.command()
def audit(
    lines: Annotated[int, typer.Option("--lines", "-n")] = 20, config: ConfigOpt = None
) -> None:
    """Show the most recent tool executions."""
    _, paths = _load(config)
    if not paths.audit_log.exists():
        console.print("No audit entries yet.")
        return
    table = Table("time", "tool", "approved by", "status", "ms", "command")
    for raw in paths.audit_log.read_text(encoding="utf-8").splitlines()[-lines:]:
        entry = json.loads(raw)
        table.add_row(
            entry["timestamp"],
            entry["tool"],
            entry["approved_by"],
            entry["status"],
            str(entry["duration_ms"]),
            " ".join(entry["argv"]),
        )
    console.print(table)


# -- eval ------------------------------------------------------------------------------------


def _print_report(report, verbose: bool) -> None:  # type: ignore[no-untyped-def]
    for result in report.results:
        if result.skipped:
            mark = "[dim]skip[/dim]"
        else:
            mark = "[green]pass[/green]" if result.passed else "[red]FAIL[/red]"
        if verbose or not result.passed:
            console.print(f"{mark} {escape(result.case.query)} [dim]{escape(result.detail)}[/dim]")
    table = Table("metric", "value")
    for name, value in report.metrics.items():
        table.add_row(name, f"{value:.2f}")
    console.print(table)


@eval_app.command("retrieval")
def eval_retrieval(
    config: ConfigOpt = None,
    cases: Annotated[Path | None, typer.Option("--cases", help="Custom golden YAML")] = None,
    embeddings: Annotated[bool, typer.Option("--embeddings/--no-embeddings")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    min_recall: Annotated[float, typer.Option("--min-recall")] = 0.85,
) -> None:
    """Score tool retrieval (no chat model needed). Add --embeddings to test the vector path."""
    settings, paths = _load(config)
    report_packs = load_packs(pack_roots(paths, settings))
    registry = registry_for_retrieval_eval(list(report_packs.tools.values()))
    embedder = build_embeddings(settings.embeddings) if embeddings and settings.embeddings else None
    index = ToolIndex(
        ":memory:",
        settings.retrieval,
        embedder,
        embedding_id=settings.embeddings.name if settings.embeddings else "",
    )
    index.sync(registry.available.values())
    console.print(
        f"mode: {'hybrid (BM25 + vectors)' if index.vectors_enabled else 'keyword only (BM25)'}"
    )
    report = evaluate_retrieval(
        list(registry.available.values()), load_cases(cases), settings.retrieval, index
    )
    _print_report(report, verbose)
    index.close()
    if report.metrics[f"recall@{settings.retrieval.top_k}"] < min_recall:
        raise typer.Exit(code=1)


@eval_app.command("agent")
def eval_agent(
    config: ConfigOpt = None,
    cases: Annotated[Path | None, typer.Option("--cases")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Only the first N cases")] = None,
) -> None:
    """Run the live agent on the golden set (commands are simulated, approvals auto-denied)."""
    settings, paths = _load(config)
    runtime = build_runtime(settings, paths, runner=SimulatedRunner())
    try:
        selected = load_cases(cases)[:limit]
        report = evaluate_agent(
            runtime.assistant,
            set(runtime.registry.available),
            selected,
            progress=lambda i, n, r: console.print(f"[dim]{i}/{n}[/dim]", end=" "),
        )
        console.print()
        _print_report(report, verbose)
    finally:
        runtime.close()


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


def _force_utf8() -> None:
    """Legacy Windows code pages cannot print the status glyphs; never crash on output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8()
    app()


if __name__ == "__main__":
    main()
