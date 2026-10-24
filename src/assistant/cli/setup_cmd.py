"""The ``setup`` command: wizard, config file, and model downloads."""

from __future__ import annotations

from pathlib import Path

import ollama
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn

from assistant.cli.prompter import RichPrompter
from assistant.config import Settings, load_settings
from assistant.domain import ConfigError
from assistant.domain.branding import APP_NAME, cmd
from assistant.llm import check_backend
from assistant.setup import (
    baseline,
    build_settings,
    detect_hardware,
    estimate_memory_gb,
    installed_tags,
    load_catalog,
    minimal_overrides,
    missing_tags,
    needed_tags,
    pull_model,
    recommend,
    run_wizard,
    summary_lines,
    write_config,
)
from assistant.setup.wizard import Mode

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


def run_setup(
    console: Console,
    config_file: Path,
    *,
    mode: Mode,
    assume_yes: bool,
    pull: bool | None,
    check_only: bool,
) -> int:
    """Returns a process exit code."""
    hardware = detect_hardware()
    catalog = load_catalog()

    if check_only:
        console.print(f"Detected: {escape(hardware.describe())}")
        for title, preview in (
            ("Default setup (same on every machine)", baseline(catalog)),
            ("Recommended setup (tailored to this machine)", recommend(hardware, catalog)),
        ):
            console.print(f"\n[bold]{title}[/bold]")
            for line in summary_lines(preview):
                console.print("  " + escape(line))
        console.print(
            f"\nRun [bold]{cmd('setup')}[/bold] to choose one; nothing is applied without confirmation."
        )
        return 0

    console.print(f"[bold]{APP_NAME} setup[/bold]")
    if config_file.exists():
        console.print(
            f"[dim]Existing configuration found at {escape(str(config_file))}. Your choices are "
            "merged into it and a backup is kept.[/dim]"
        )
    prompter = RichPrompter(console, assume_yes=assume_yes)
    choices = run_wizard(prompter, hardware, catalog, mode=mode)
    if choices is None:
        console.print("Setup cancelled. Nothing was changed.")
        return 1

    settings = build_settings(choices)
    backup = write_config(config_file, minimal_overrides(settings))
    try:
        settings = load_settings(config_file)  # prove the written file is valid
    except ConfigError as exc:
        console.print(
            f"[bold red]The written configuration is invalid:[/bold red] {escape(str(exc))}"
        )
        return 1
    console.print(f"[green]Saved[/green] {escape(str(config_file))}")
    if backup is not None:
        console.print(f"[dim]Previous version kept at {escape(str(backup))}[/dim]")
    console.print(
        f"[dim]Estimated memory with everything loaded: about {estimate_memory_gb(choices):.1f} GB[/dim]"
    )

    _download_models(
        console,
        settings,
        catalog_sizes={m.tag: m.download_gb for m in catalog.models},
        pull=pull,
        assume_yes=assume_yes,
        prompter=prompter,
    )
    _report(console, settings)
    return 0


def _download_models(
    console: Console,
    settings: Settings,
    *,
    catalog_sizes: dict[str, float],
    pull: bool | None,
    assume_yes: bool,
    prompter: RichPrompter,
) -> None:
    host = settings.models["main"].base_url
    client = ollama.Client(host=host, timeout=10.0)
    try:
        installed = installed_tags(client)
    except Exception:
        console.print(
            f"[yellow]Ollama is not reachable at {escape(host)}.[/yellow] Install it from "
            f"{OLLAMA_DOWNLOAD_URL}, start it, then run [bold]{cmd('doctor')}[/bold]."
        )
        return

    missing = missing_tags(needed_tags(settings), installed)
    if not missing:
        console.print("All required models are already downloaded.")
        return
    total = sum(catalog_sizes.get(tag, 0.0) for tag in missing)
    listing = ", ".join(missing)
    console.print(f"Models to download: {escape(listing)} (about {total:.1f} GB)")
    if pull is None:
        if assume_yes:
            console.print(
                f"Skipping download (use --pull to allow it, or run: ollama pull {missing[0]})."
            )
            return
        pull = prompter.confirm("Download them now?", default=True)
    if not pull:
        console.print(
            "Skipped. Download later with: " + "; ".join(f"ollama pull {t}" for t in missing)
        )
        return

    long_client = ollama.Client(host=host, timeout=None)
    for tag in missing:
        _pull_with_progress(console, long_client, tag)


def _pull_with_progress(console: Console, client: ollama.Client, tag: str) -> None:
    columns = (TextColumn("{task.description}"), BarColumn(), DownloadColumn())
    with Progress(*columns, console=console) as progress:
        task = progress.add_task(f"{tag}", total=None)

        def on_progress(status: str, total: int | None, completed: int | None) -> None:
            progress.update(
                task,
                description=f"{tag}: {status[:32]}",
                total=total,
                completed=completed or 0,
            )

        try:
            pull_model(client, tag, on_progress)
        except Exception as exc:
            console.print(f"[red]Could not download {escape(tag)}:[/red] {escape(str(exc))}")


def _report(console: Console, settings: Settings) -> None:
    problems = [c for c in check_backend(settings) if not c.ok]
    if not problems:
        console.print(f"\n[bold green]All set.[/bold green] Start with [bold]{cmd('chat')}[/bold].")
        return
    console.print("\nSetup is saved, but a few things need attention:")
    for check in problems:
        console.print(f"  [yellow]•[/yellow] {escape(check.name)}: {escape(check.detail)}")
    console.print(f"Run [bold]{cmd('doctor')}[/bold] for details.")
