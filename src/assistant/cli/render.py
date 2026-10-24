"""Rich rendering of service events. Contains presentation only, no business rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from assistant.domain import (
    ApprovalMode,
    ApprovalRequest,
    ApprovalRequestedEvent,
    ErrorEvent,
    Event,
    FinalEvent,
    RiskLevel,
    TokenEvent,
    ToolProposedEvent,
    ToolResultEvent,
)

_RISK_STYLE = {
    RiskLevel.READ_ONLY: "green",
    RiskLevel.MUTATING: "yellow",
    RiskLevel.DESTRUCTIVE: "bold red",
}
_STATUS_ICON = {
    "ok": "[green]✓[/green]",
    "error": "[red]✗[/red]",
    "timeout": "[red]⏱[/red]",
    "denied": "[yellow]⊘[/yellow]",
}

Decider = Callable[[ApprovalRequest], bool]


class ConsoleRenderer:
    """Stateful per-turn renderer (tracks whether text was already streamed)."""

    def __init__(self, console: Console, *, show_tool_output: bool = False) -> None:
        self.console = console
        self.show_tool_output = show_tool_output
        self._streamed = False

    def begin_turn(self) -> None:
        self._streamed = False

    def render(self, event: Event) -> ApprovalRequestedEvent | None:
        """Render one event; returns the approval request when the turn is paused on one."""
        if isinstance(event, TokenEvent):
            if not self._streamed:
                self.console.print("[bold magenta]Assistant:[/bold magenta] ", end="")
                self._streamed = True
            self.console.print(event.text, end="", markup=False, highlight=False)
        elif isinstance(event, ToolProposedEvent):
            self.console.print(
                f"[dim]→ {escape(event.tool)}[/dim] [{_RISK_STYLE[event.risk]}]({event.risk.value})[/]"
                f" [dim]{escape(event.command)}[/dim]"
            )
        elif isinstance(event, ToolResultEvent):
            icon = _STATUS_ICON.get(event.status, "?")
            self.console.print(f"[dim]  {icon} {escape(event.tool)} · {event.duration_ms} ms[/dim]")
            if self.show_tool_output or event.status != "ok":
                self.console.print(Panel(escape(event.output) or "(no output)", border_style="dim"))
        elif isinstance(event, FinalEvent):
            if self._streamed:
                self.console.print()
            elif event.text:
                self.console.print(f"[bold magenta]Assistant:[/bold magenta] {escape(event.text)}")
        elif isinstance(event, ErrorEvent):
            if self._streamed:
                self.console.print()
            self.console.print(f"[bold red]Error:[/bold red] {escape(event.message)}")
        elif isinstance(event, ApprovalRequestedEvent):
            if self._streamed:
                self.console.print()
            return event
        return None

    def run_events(self, events: Iterable[Event]) -> ApprovalRequestedEvent | None:
        """Render a whole event stream, showing a spinner while waiting for the model or a tool."""
        pending: ApprovalRequestedEvent | None = None
        status = self.console.status("[dim]thinking…[/dim]")
        status.start()
        try:
            for event in events:
                status.stop()
                pending = self.render(event) or pending
                if not isinstance(
                    event, TokenEvent | FinalEvent | ErrorEvent | ApprovalRequestedEvent
                ):
                    status.start()  # a tool is running or the next model call is starting
        finally:
            status.stop()
        return pending

    # -- approvals ---------------------------------------------------------------------------

    def ask_approvals(self, request: ApprovalRequestedEvent) -> dict[str, bool]:
        return {r.call_id: self._ask_one(r) for r in request.requests}

    def _ask_one(self, request: ApprovalRequest) -> bool:
        style = _RISK_STYLE[request.risk]
        lines = [
            f"[bold]{escape(request.tool)}[/bold]  [{style}]{request.risk.value}[/]",
            f"[dim]command:[/dim] {escape(request.command)}",
        ]
        if request.message:
            lines.append(f"[yellow]{escape(request.message)}[/yellow]")
        self.console.print(Panel("\n".join(lines), title="Approval needed", border_style=style))
        if request.mode is ApprovalMode.CONFIRM:
            answer = Prompt.ask(
                f"Type [bold]{request.tool}[/bold] to run it (anything else cancels)"
            )
            return answer.strip() == request.tool
        return Confirm.ask("Run it?", default=False)
