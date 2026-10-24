"""Result of running an external command."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of one command execution. Output is already bounded and decoded."""

    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None  # launch failure, e.g. executable not found

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out and self.exit_code == 0

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.timed_out:
            return "timeout"
        return "ok" if self.exit_code == 0 else "error"

    def render(self) -> str:
        """Human/LLM-readable text including failure context."""
        if self.error:
            return f"Error: {self.error}"
        parts: list[str] = []
        if self.timed_out:
            parts.append(f"Command timed out after {self.duration_s:.0f}s and was terminated.")
        elif self.exit_code not in (0, None):
            parts.append(f"Command exited with code {self.exit_code}.")
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.strip()}")
        if self.truncated:
            parts.append("[output truncated]")
        return "\n".join(parts) or "Command completed with no output."
