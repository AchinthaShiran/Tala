"""Best-effort hardware detection for the setup wizard (standard library only).

Detection never raises: anything that cannot be determined is reported as unknown, and the wizard
then falls back to conservative advice.
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

_T = TypeVar("_T")
_GB = 1024**3
_CPU_BUDGET = 0.7  # share of RAM a model may use before everything else gets squeezed
_UNIFIED_BUDGET = 0.7


@dataclass(frozen=True, slots=True)
class Hardware:
    system: str
    ram_gb: float | None = None
    cpu_threads: int | None = None
    gpu_name: str | None = None
    vram_gb: float | None = None
    unified_memory: bool = False  # Apple Silicon: CPU and GPU share RAM

    @property
    def accelerated(self) -> bool:
        return self.vram_gb is not None or self.unified_memory

    @property
    def budget_gb(self) -> float | None:
        """Memory a model can realistically use: VRAM on a discrete GPU, most of RAM otherwise."""
        if self.vram_gb is not None:
            return self.vram_gb
        if self.ram_gb is None:
            return None
        return self.ram_gb * (_UNIFIED_BUDGET if self.unified_memory else _CPU_BUDGET)

    def describe(self) -> str:
        parts = [self.system]
        if self.ram_gb is not None:
            parts.append(f"{self.ram_gb:.1f} GB RAM")
        if self.cpu_threads:
            parts.append(f"{self.cpu_threads} CPU threads")
        if self.gpu_name and self.vram_gb is not None:
            parts.append(f"GPU {self.gpu_name} ({self.vram_gb:.0f} GB)")
        elif self.unified_memory:
            parts.append("Apple Silicon (unified memory)")
        else:
            parts.append("no supported GPU detected")
        return ", ".join(parts)


def parse_meminfo(text: str) -> float | None:
    """GB from the contents of /proc/meminfo."""
    match = re.search(r"^MemTotal:\s+(\d+)\s*kB", text, re.MULTILINE)
    return int(match.group(1)) * 1024 / _GB if match else None


def parse_nvidia_smi(text: str) -> tuple[str, float] | None:
    """(name, GB) of the largest GPU from ``nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits``."""
    best: tuple[str, float] | None = None
    for line in text.splitlines():
        name, _, memory = line.rpartition(",")
        if not name or not memory.strip().isdigit():
            continue
        gb = int(memory.strip()) / 1024
        if best is None or gb > best[1]:
            best = (name.strip(), gb)
    return best


def _ram_windows() -> float | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined,unused-ignore]
    return status.ullTotalPhys / _GB if ok else None


def _ram_linux() -> float | None:
    with open("/proc/meminfo", encoding="utf-8") as handle:
        return parse_meminfo(handle.read())


def _ram_macos() -> float | None:
    out = subprocess.run(
        ["sysctl", "-n", "hw.memsize"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).stdout.strip()
    return int(out) / _GB if out.isdigit() else None


def _run_nvidia_smi() -> str:
    return subprocess.run(
        [  # noqa: S607
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    ).stdout


def _safely(probe: Callable[[], _T]) -> _T | None:
    try:
        return probe()
    except Exception:
        return None


def detect_hardware(
    *,
    platform_name: str | None = None,
    machine: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    ram_probe: Callable[[], float | None] | None = None,
    smi_probe: Callable[[], str] = _run_nvidia_smi,
) -> Hardware:
    """Inspect this machine. Every argument exists so tests can simulate other hardware."""
    name = platform_name or sys.platform
    arch = (machine or platform.machine()).lower()
    if ram_probe is None:
        ram_probe = (
            _ram_windows
            if name.startswith("win")
            else _ram_macos
            if name == "darwin"
            else _ram_linux
        )
    ram = _safely(ram_probe)

    gpu: tuple[str, float] | None = None
    if which("nvidia-smi"):
        output = _safely(smi_probe)
        gpu = parse_nvidia_smi(output) if output else None

    system = {"darwin": "macOS", "linux": "Linux"}.get(
        name, "Windows" if name.startswith("win") else name
    )
    return Hardware(
        system=system,
        ram_gb=ram,
        cpu_threads=os.cpu_count(),
        gpu_name=gpu[0] if gpu else None,
        vram_gb=gpu[1] if gpu else None,
        unified_memory=name == "darwin" and arch in {"arm64", "aarch64"},
    )
