"""What the pet notices about the computer: battery level and charging (toolkit-free).

``read_power`` asks the operating system; ``PowerWatcher`` turns a stream of readings into the few
moments worth telling the user about, so both can be tested without a battery.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

LOW_PERCENT = 20  # at or below this, on battery: tired
CRITICAL_PERCENT = 10
RECOVERED_PERCENT = 25  # climbing back above this re-arms the low-battery warning


@dataclass(frozen=True)
class PowerStatus:
    percent: int  # 0 to 100
    plugged_in: bool


@dataclass(frozen=True)
class PowerNotice:
    kind: str  # "low", "critical", "plugged", "unplugged", "full"
    text: str


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def _read_windows() -> PowerStatus | None:
    status = _SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):  # type: ignore[attr-defined,unused-ignore]
        return None
    if status.BatteryFlag == 128 or status.BatteryLifePercent > 100:  # no battery / unknown
        return None
    return PowerStatus(int(status.BatteryLifePercent), status.ACLineStatus == 1)


def _read_linux() -> PowerStatus | None:
    for battery in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            percent = int((battery / "capacity").read_text().strip())
            state = (battery / "status").read_text().strip().lower()
        except (OSError, ValueError):
            continue
        return PowerStatus(percent, state != "discharging")
    return None


def read_power() -> PowerStatus | None:
    """The battery now, or None on a machine without one (a desktop PC) or when unreadable."""
    try:
        if sys.platform == "win32":
            return _read_windows()
        if sys.platform.startswith("linux"):
            return _read_linux()
    except Exception:
        return None
    return None


class PowerWatcher:
    """Remembers the last reading and reports what changed."""

    def __init__(self) -> None:
        self._last: PowerStatus | None = None
        self._warned_low = False
        self._warned_critical = False
        self._announced_full = False

    @property
    def tired(self) -> bool:
        """On battery and low: the pet should look tired."""
        last = self._last
        return last is not None and not last.plugged_in and last.percent <= LOW_PERCENT

    def update(self, status: PowerStatus | None) -> list[PowerNotice]:
        if status is None:
            self._last = None
            return []
        previous, self._last = self._last, status
        notices: list[PowerNotice] = []
        if previous is not None and status.plugged_in != previous.plugged_in:
            if status.plugged_in:
                notices.append(PowerNotice("plugged", f"Charging. Battery at {status.percent}%."))
            else:
                notices.append(PowerNotice("unplugged", f"Running on battery ({status.percent}%)."))
        if status.plugged_in or status.percent >= RECOVERED_PERCENT:
            self._warned_low = self._warned_critical = False
        if status.percent < 100 or not status.plugged_in:
            self._announced_full = False
        if not status.plugged_in:
            if status.percent <= CRITICAL_PERCENT and not self._warned_critical:
                self._warned_critical = self._warned_low = True
                notices.append(
                    PowerNotice(
                        "critical",
                        f"Battery is nearly empty ({status.percent}%). Please plug me in!",
                    )
                )
            elif status.percent <= LOW_PERCENT and not self._warned_low:
                self._warned_low = True
                notices.append(
                    PowerNotice("low", f"Battery is low ({status.percent}%). I'm getting tired...")
                )
        elif status.percent >= 100 and not self._announced_full:
            self._announced_full = True
            notices.append(PowerNotice("full", "Battery is full. You can unplug me."))
        return notices
