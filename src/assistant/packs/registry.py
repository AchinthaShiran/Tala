"""Which loaded tools can really run on this machine."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from assistant.domain import Platform, ToolNotAvailableError, ToolSpec

Which = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class Unavailable:
    tool: ToolSpec
    reason: str


class ToolRegistry:
    """Partitions tools into runnable and unavailable-with-reason for one platform."""

    def __init__(
        self, tools: Iterable[ToolSpec], platform: Platform, which: Which = shutil.which
    ) -> None:
        self.platform = platform
        self._which = which
        self._available: dict[str, ToolSpec] = {}
        self._unavailable: dict[str, Unavailable] = {}
        for spec in tools:
            reason = self._why_not(spec)
            if reason is None:
                self._available[spec.name] = spec
            else:
                self._unavailable[spec.name] = Unavailable(spec, reason)

    def _why_not(self, spec: ToolSpec) -> str | None:
        variant = spec.variant_for(self.platform)
        if variant is None:
            return f"no variant for {self.platform.value}"
        if self._which(variant.exe) is None:
            return f"executable '{variant.exe}' not found on PATH"
        return None

    @property
    def available(self) -> dict[str, ToolSpec]:
        return dict(self._available)

    @property
    def unavailable(self) -> dict[str, Unavailable]:
        return dict(self._unavailable)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._available[name]
        except KeyError:
            unavailable = self._unavailable.get(name)
            detail = f": {unavailable.reason}" if unavailable else ""
            raise ToolNotAvailableError(f"tool '{name}' is not available{detail}") from None

    def resolve_executable(self, spec: ToolSpec) -> str:
        """Absolute path of the executable for the current platform."""
        variant = spec.variant_for(self.platform)
        path = self._which(variant.exe) if variant else None
        if path is None:
            raise ToolNotAvailableError(f"tool '{spec.name}': executable not found")
        return path

    def __contains__(self, name: object) -> bool:
        return name in self._available

    def __len__(self) -> int:
        return len(self._available)
