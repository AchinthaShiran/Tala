"""Operating-system identification used for pack variant selection."""

from __future__ import annotations

import sys
from enum import StrEnum


class Platform(StrEnum):
    """Platforms a tool variant can target. ``ANY`` matches every OS."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANY = "any"


def current_platform() -> Platform:
    """Return the concrete platform of the running interpreter."""
    if sys.platform.startswith("win"):
        return Platform.WINDOWS
    if sys.platform == "darwin":
        return Platform.MACOS
    return Platform.LINUX
