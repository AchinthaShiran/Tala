"""Desktop pet entry point: wires the pet, chat window, tray icon and the assistant worker."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from assistant import __version__
from assistant.bootstrap import Runtime, build_runtime
from assistant.config import AppPaths, default_paths, load_settings
from assistant.domain import ApprovalRequestedEvent, ErrorEvent, Event, FinalEvent
from assistant.domain.branding import APP_NAME
from assistant.ui.characters import CharacterError, SpriteSet, discover, load_character
from assistant.ui.chat import ChatWindow
from assistant.ui.config_store import ConfigStore
from assistant.ui.notice import NoticeBubble
from assistant.ui.pet import PetWidget, render_icon
from assistant.ui.settings_dialog import SettingsDialog
from assistant.ui.state import Emotion, Mood, emotion_for, mood_for
from assistant.ui.system import PowerNotice, PowerStatus, PowerWatcher, read_power
from assistant.ui.vector_characters import CHARACTERS, ROBOT, VectorCharacter
from assistant.ui.worker import AssistantWorker

_NOTICE_CHARS = 120
_POWER_POLL_MS = 20_000


class DesktopPet(QObject):
    """Owns the windows and the worker thread; the only place UI and assistant meet."""

    _start = Signal()
    _send = Signal(str)
    _resume = Signal(object)
    _reset = Signal()
    _shutdown = Signal()
    _restart = Signal()

    def __init__(
        self,
        app: QApplication,
        factory: Callable[[], Runtime],
        *,
        session: str = "default",
        settings: QSettings | None = None,
        config_store: ConfigStore | None = None,
        paths: AppPaths | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._config_store = config_store
        self._paths = paths
        self._dialog: SettingsDialog | None = None
        self._applying = False
        settings = settings or QSettings(APP_NAME, f"{APP_NAME} Desktop")
        self._qsettings = settings
        saved = str(settings.value("pet/character", "") or "")
        self.pet = PetWidget(settings, *(self._resolve_character(saved) or (None, ROBOT)))
        self.chat = ChatWindow(APP_NAME)
        self.bubble = NoticeBubble()
        self._power = PowerWatcher()
        self._power_reader: Callable[[], PowerStatus | None] = read_power
        self._power_timer = QTimer(self)
        self._power_timer.setInterval(_POWER_POLL_MS)
        self._power_timer.timeout.connect(self.check_power)
        self.tray = self._build_tray()
        self.pet.set_menu(self._build_menu())
        self.pet.setWindowTitle(APP_NAME)
        self.chat.setWindowTitle(APP_NAME)

        self._thread = QThread()
        self._worker = AssistantWorker(factory, session)
        self._worker.moveToThread(self._thread)
        self._connect()

    # -- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()
        self._start.emit()
        self.pet.show()
        if self.tray is not None:
            self.tray.show()
        self.check_power()
        self._power_timer.start()

    def quit(self) -> None:
        self._shutdown.emit()  # closes the runtime on the thread that owns it, then stops the loop
        if not self._thread.wait(5000):  # a model call that never returns must not hang exit
            self._thread.terminate()
            self._thread.wait(1000)
        if self.tray is not None:
            self.tray.hide()
        self._power_timer.stop()
        self.bubble.clear()
        self.bubble.hide()
        self.chat.hide()
        self.pet.hide()
        self._app.quit()

    # -- wiring ------------------------------------------------------------------------------

    def _connect(self) -> None:
        worker, chat, pet = self._worker, self.chat, self.pet
        self._start.connect(worker.start)
        self._send.connect(worker.send)
        self._resume.connect(worker.resume)
        self._reset.connect(worker.reset)
        self._shutdown.connect(worker.shutdown)
        self._restart.connect(worker.restart)

        worker.ready.connect(self._on_ready)
        worker.failed.connect(self._on_failed)
        worker.history.connect(chat.show_history)
        worker.emitted.connect(self._on_event)

        chat.message_submitted.connect(self._on_submit)
        chat.decisions_made.connect(self._on_decisions)
        chat.settings_requested.connect(self.open_settings)
        chat.hidden_by_user.connect(lambda: self._sync_toggle())
        pet.clicked.connect(self.toggle_chat)
        pet.moved.connect(self._follow_pet)
        self.bubble.clicked.connect(self.show_chat)

    def _build_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(QIcon(render_icon()), self)
        tray.setToolTip(APP_NAME)
        tray.activated.connect(self._on_tray_activated)
        return tray

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        self._toggle_action = QAction("Open chat", menu)
        self._toggle_action.triggered.connect(self.toggle_chat)
        new = QAction("New conversation", menu)
        new.triggered.connect(self.new_conversation)
        settings_action = QAction("Settings…", menu)
        settings_action.setEnabled(self._config_store is not None)
        settings_action.triggered.connect(self.open_settings)
        self._battery_action = QAction("Battery alerts", menu)
        self._battery_action.setCheckable(True)
        self._battery_action.setChecked(self._battery_alerts)
        self._battery_action.toggled.connect(self._set_battery_alerts)
        about = QAction(f"{APP_NAME} {__version__}", menu)
        about.setEnabled(False)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self.quit)
        for action in (self._toggle_action, new, settings_action, self._battery_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(about)
        menu.addAction(quit_)
        self._menu = menu
        if self.tray is not None:
            self.tray.setContextMenu(menu)
        return menu

    # -- slots -------------------------------------------------------------------------------

    def toggle_chat(self) -> None:
        if self.chat.is_open:
            self.chat.hide_chat()
        else:
            self.show_chat()

    def show_chat(self) -> None:
        self.pet.set_attention(False)
        self.chat.present(self.pet.geometry())
        self._sync_toggle()

    def new_conversation(self) -> None:
        if self.chat.is_busy:
            self._notify("Please wait until I finish the current request.")
            return
        self._reset.emit()
        self.chat.clear()
        self.chat.add_note("Fresh start. What can I do for you?")

    def open_settings(self) -> None:
        """Show the settings window (one at a time); saving restarts the assistant."""
        if self._config_store is None or self._paths is None:
            return
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        dialog = SettingsDialog(
            self._config_store,
            self._paths,
            current_character=str(self._qsettings.value("pet/character", "") or ""),
            current_size=self.pet.size_px,
        )
        dialog.saved.connect(self._apply_settings)
        dialog.character_selected.connect(self.select_character)
        dialog.size_selected.connect(self.pet.set_size)
        dialog.new_conversation_requested.connect(self.new_conversation)
        dialog.finished.connect(lambda _r: setattr(self, "_dialog", None))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _resolve_character(self, name: str) -> tuple[SpriteSet | None, VectorCharacter] | None:
        """What to draw for a saved choice: ("" = robot, "builtin:key", or an image pack folder).

        Returns None when the choice cannot be used (unknown name, unreadable pack).
        """
        if not name:
            return None, ROBOT
        if name.startswith("builtin:"):
            character = CHARACTERS.get(name[len("builtin:") :])
            return (None, character) if character is not None else None
        if self._paths is None:
            return None
        folder = discover(self._paths.characters_dir).get(
            name
        )  # only known folders: no path tricks
        if folder is None:
            return None
        try:
            return load_character(folder), ROBOT
        except CharacterError:
            return None

    def select_character(self, name: str) -> None:
        """Switch the pet's look and remember it."""
        resolved = self._resolve_character(name)
        if resolved is None:
            self.chat.add_error(
                f"Could not load the character \u201c{name}\u201d; keeping the current one."
            )
            return
        sprites, vector = resolved
        self._qsettings.setValue("pet/character", name)
        self.pet.set_character(sprites, vector)
        if self.tray is not None:
            self.tray.setIcon(QIcon(render_icon(sprites=sprites, vector=vector)))

    def _apply_settings(self) -> None:
        self._applying = True
        self.chat.set_loading("Applying settings…")
        self._set_mood(Mood.THINKING)
        self._restart.emit()

    def _sync_toggle(self) -> None:
        self._toggle_action.setText("Hide chat" if self.chat.is_open else "Open chat")

    @property
    def _battery_alerts(self) -> bool:
        return str(self._qsettings.value("pet/battery_alerts", "true")).lower() != "false"

    def _set_battery_alerts(self, on: bool) -> None:
        self._qsettings.setValue("pet/battery_alerts", "true" if on else "false")
        self.check_power()

    def check_power(self) -> None:
        """Look at the battery: tired when low, and say something when it matters."""
        if not self._battery_alerts:
            self._power.update(None)
            self.pet.set_tired(False)
            return
        notices = self._power.update(self._power_reader())
        self.pet.set_tired(self._power.tired)
        for notice in notices:
            self._announce_power(notice)

    def _announce_power(self, notice: PowerNotice) -> None:
        self.bubble.anchor_to(self.pet.geometry())
        self.bubble.notify(notice.text, notice.kind)
        if notice.kind in ("plugged", "full"):
            self.pet.react(Emotion.CHARGING, 3.5)
            self.pet.hop(0.4)
        elif notice.kind in ("low", "critical"):
            self.pet.react(Emotion.SURPRISED, 0.8)
            self.pet.hop(0.5)

    def _follow_pet(self) -> None:
        self.bubble.anchor_to(self.pet.geometry())
        if self.chat.is_open:
            self.chat.anchor_to(self.pet.geometry())

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.pet.show()
            self.toggle_chat()

    def _on_ready(self, tool_count: int) -> None:
        self.chat.set_ready(tool_count)
        self.pet.set_mood(Mood.IDLE)
        if self._applying:
            self._applying = False
            self.chat.add_note("Settings applied.")

    def _on_failed(self, message: str) -> None:
        self._applying = False
        self.chat.set_failed(message)
        self.pet.set_mood(Mood.ERROR)
        self._alert("Could not start", message)

    def _on_submit(self, text: str) -> None:
        self._set_mood(Mood.THINKING)
        self._send.emit(text)

    def _on_decisions(self, decisions: object) -> None:
        self.chat.begin_busy()
        self._set_mood(Mood.THINKING)
        self._resume.emit(decisions)

    def _on_event(self, event: Event) -> None:
        self._set_mood(mood_for(event))
        reaction = emotion_for(event)
        if reaction is not None:
            self.pet.react(*reaction)
        self.chat.handle_event(event)
        if self.chat.is_open:
            return
        if isinstance(event, ApprovalRequestedEvent):
            self.show_chat()  # a decision is needed; never leave it buried
            self._alert("Approval needed", "A tool wants to run a command.")
        elif isinstance(event, FinalEvent) and event.text:
            self._alert(APP_NAME, event.text)
        elif isinstance(event, ErrorEvent):
            self._alert("Something went wrong", event.message)

    def _set_mood(self, mood: Mood) -> None:
        self.pet.set_mood(mood)
        self.chat.set_mood(mood)

    def _alert(self, title: str, text: str) -> None:
        """Attract attention while the chat is closed: badge on the pet plus a tray balloon."""
        if not self.chat.is_open:
            self.pet.set_attention(True)
        self._notify(text, title)

    def _notify(self, text: str, title: str = APP_NAME) -> None:
        short = text if len(text) <= _NOTICE_CHARS else text[: _NOTICE_CHARS - 1] + "…"
        if self.pet.isVisible():  # the pet speaks for itself; the tray is the fallback
            self.bubble.anchor_to(self.pet.geometry())
            self.bubble.notify(short if title == APP_NAME else f"{title}: {short}")
        elif self.tray is not None:
            self.tray.showMessage(title, short, QSystemTrayIcon.MessageIcon.NoIcon, 6000)


def run_ui(config: Path | None = None, session: str = "default") -> int:
    """Start the desktop pet; returns the process exit code."""
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # the pet and tray outlive the chat window
    app.setWindowIcon(QIcon(render_icon()))

    config_file = config or default_paths().config_file
    settings = load_settings(config_file)
    paths = default_paths(settings.data_dir)
    paths.ensure()
    lock = QLockFile(str(paths.data_dir / "desktop.lock"))
    if not lock.tryLock(0):
        print(f"{APP_NAME} is already running on the desktop.", file=sys.stderr)
        return 1

    def build() -> Runtime:
        # Re-read the file each time so a restart after the settings page picks up the changes.
        fresh = load_settings(config_file)
        return build_runtime(fresh, default_paths(fresh.data_dir))

    pet = DesktopPet(
        app,
        build,
        session=session,
        config_store=ConfigStore(config_file),
        paths=paths,
    )
    pet.start()
    code = app.exec()
    lock.unlock()
    return code


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=f"{APP_NAME.lower()}-ui", description="Desktop pet.")
    parser.add_argument("--config", "-c", type=Path, help="Path to a config.yaml")
    parser.add_argument("--session", "-s", default="default", help="Session name (resumable)")
    args = parser.parse_args(argv)
    sys.exit(run_ui(args.config, args.session))


if __name__ == "__main__":
    main()
