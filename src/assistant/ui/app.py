"""Desktop pet entry point: wires the pet, chat window, tray icon and the assistant worker."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QSettings, QThread, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from assistant import __version__
from assistant.bootstrap import Runtime, build_runtime
from assistant.config import default_paths, load_settings
from assistant.domain import ApprovalRequestedEvent, ErrorEvent, Event, FinalEvent
from assistant.domain.branding import APP_NAME
from assistant.ui.chat import ChatWindow
from assistant.ui.pet import PetWidget, render_icon
from assistant.ui.state import Mood, mood_for
from assistant.ui.worker import AssistantWorker

_NOTICE_CHARS = 120


class DesktopPet(QObject):
    """Owns the windows and the worker thread; the only place UI and assistant meet."""

    _start = Signal()
    _send = Signal(str)
    _resume = Signal(object)
    _reset = Signal()
    _shutdown = Signal()

    def __init__(
        self,
        app: QApplication,
        factory: Callable[[], Runtime],
        *,
        session: str = "default",
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        settings = settings or QSettings(APP_NAME, f"{APP_NAME} Desktop")
        self.pet = PetWidget(settings)
        self.chat = ChatWindow(APP_NAME)
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

    def quit(self) -> None:
        self._shutdown.emit()  # closes the runtime on the thread that owns it, then stops the loop
        if not self._thread.wait(5000):  # a model call that never returns must not hang exit
            self._thread.terminate()
            self._thread.wait(1000)
        if self.tray is not None:
            self.tray.hide()
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

        worker.ready.connect(self._on_ready)
        worker.failed.connect(self._on_failed)
        worker.history.connect(chat.show_history)
        worker.emitted.connect(self._on_event)

        chat.message_submitted.connect(self._on_submit)
        chat.decisions_made.connect(self._on_decisions)
        chat.hidden_by_user.connect(lambda: self._sync_toggle())
        pet.clicked.connect(self.toggle_chat)
        pet.moved.connect(self._follow_pet)

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
        about = QAction(f"{APP_NAME} {__version__}", menu)
        about.setEnabled(False)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self.quit)
        for action in (self._toggle_action, new):
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
        if self.chat.isVisible():
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

    def _sync_toggle(self) -> None:
        self._toggle_action.setText("Hide chat" if self.chat.isVisible() else "Open chat")

    def _follow_pet(self) -> None:
        if self.chat.isVisible():
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

    def _on_failed(self, message: str) -> None:
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
        self.chat.handle_event(event)
        if self.chat.isVisible():
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
        if not self.chat.isVisible():
            self.pet.set_attention(True)
        self._notify(text, title)

    def _notify(self, text: str, title: str = APP_NAME) -> None:
        if self.tray is not None:
            short = text if len(text) <= _NOTICE_CHARS else text[: _NOTICE_CHARS - 1] + "…"
            self.tray.showMessage(title, short, QSystemTrayIcon.MessageIcon.NoIcon, 6000)


def run_ui(config: Path | None = None, session: str = "default") -> int:
    """Start the desktop pet; returns the process exit code."""
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # the pet and tray outlive the chat window
    app.setWindowIcon(QIcon(render_icon()))

    settings = load_settings(config or default_paths().config_file)
    paths = default_paths(settings.data_dir)
    paths.ensure()
    lock = QLockFile(str(paths.data_dir / "desktop.lock"))
    if not lock.tryLock(0):
        print(f"{APP_NAME} is already running on the desktop.", file=sys.stderr)
        return 1

    pet = DesktopPet(app, lambda: build_runtime(settings, paths), session=session)
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
