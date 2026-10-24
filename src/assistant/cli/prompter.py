"""Rich-based implementation of the setup wizard's ``Prompter``."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm, IntPrompt

from assistant.setup import Option


class RichPrompter:
    """Numbered menus and yes/no questions. With ``assume_yes`` it answers every question itself."""

    def __init__(self, console: Console, *, assume_yes: bool = False) -> None:
        self._console = console
        self._assume_yes = assume_yes

    def say(self, text: str) -> None:
        self._console.print(escape(text))

    def warn(self, text: str) -> None:
        self._console.print(f"[yellow]⚠ {escape(text)}[/yellow]")

    def choose(self, question: str, options: Sequence[Option], default: int = 0) -> str:
        self._console.print(f"\n[bold]{escape(question)}[/bold]")
        for number, option in enumerate(options, start=1):
            self._console.print(f"  [cyan]{number}[/cyan]. {escape(option.label)}")
            if option.detail:
                self._console.print(f"     [dim]{escape(option.detail)}[/dim]")
        if self._assume_yes:
            return options[default].key
        picked = IntPrompt.ask(
            "Choose",
            choices=[str(n) for n in range(1, len(options) + 1)],
            default=default + 1,
            console=self._console,
        )
        return options[picked - 1].key

    def confirm(self, question: str, default: bool = True) -> bool:
        if self._assume_yes:
            self._console.print(
                f"{escape(question)} [dim]{'yes' if default else 'no'} (--yes)[/dim]"
            )
            return default
        return Confirm.ask(escape(question), default=default, console=self._console)
