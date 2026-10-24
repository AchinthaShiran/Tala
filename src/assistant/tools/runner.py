"""Shell-free subprocess execution with timeouts, tree-kill and bounded output capture."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from typing import IO, Protocol

from assistant.domain import ExecutionResult

_OMITTED = b"\n[... output omitted ...]\n"


class CommandRunner(Protocol):
    """Port for running a command. Tests substitute a fake."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> ExecutionResult: ...


class _BoundedBuffer:
    """Keeps the first and last ``limit/2`` bytes of a stream so memory stays constant."""

    def __init__(self, limit: int) -> None:
        self._half = max(limit // 2, 1)
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0

    def feed(self, chunk: bytes) -> None:
        self._total += len(chunk)
        room = self._half - len(self._head)
        if room > 0:
            self._head += chunk[:room]
            chunk = chunk[room:]
        if chunk:
            self._tail += chunk
            overflow = len(self._tail) - self._half
            if overflow > 0:
                del self._tail[:overflow]

    @property
    def truncated(self) -> bool:
        return self._total > len(self._head) + len(self._tail)

    def text(self, encoding: str) -> str:
        data = bytes(self._head)
        if self.truncated:
            data += _OMITTED
        data += bytes(self._tail)
        return data.decode(resolve_encoding(encoding), errors="replace")


def resolve_encoding(name: str) -> str:
    """Map ``oem`` to the Windows console code page; pass other names through."""
    if name.lower() != "oem":
        return name
    if sys.platform.startswith("win"):
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"  # type: ignore[attr-defined,unused-ignore]
    return "utf-8"


def _pump(stream: IO[bytes], sink: _BoundedBuffer) -> None:
    with contextlib.suppress(OSError, ValueError):
        while chunk := stream.read1(8192):  # type: ignore[attr-defined]
            sink.feed(chunk)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(OSError, ProcessLookupError):
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],  # noqa: S607
                capture_output=True,
                check=False,
                timeout=10,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _spawn(argv: Sequence[str]) -> subprocess.Popen[bytes]:
    """Start a shell-free child in its own group/session so the whole tree can be killed."""
    command = list(argv)
    if sys.platform.startswith("win"):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined,unused-ignore]
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=flags,
        )
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
    )


class SubprocessRunner:
    """Default ``CommandRunner``. Never uses a shell; stdin is closed."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> ExecutionResult:
        started = time.monotonic()
        try:
            proc = _spawn(argv)
        except OSError as exc:
            return ExecutionResult(
                tuple(argv), None, "", "", time.monotonic() - started, error=f"cannot start: {exc}"
            )

        out, err = _BoundedBuffer(max_bytes), _BoundedBuffer(max_bytes // 4 or 1)
        assert proc.stdout is not None and proc.stderr is not None
        threads = [
            threading.Thread(target=_pump, args=(proc.stdout, out), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, err), daemon=True),
        ]
        for thread in threads:
            thread.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=2)

        return ExecutionResult(
            argv=tuple(argv),
            exit_code=None if timed_out else proc.returncode,
            stdout=out.text(encoding),
            stderr=err.text(encoding),
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            truncated=out.truncated or err.truncated,
        )
