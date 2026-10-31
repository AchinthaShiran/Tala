"""Runs the assistant on its own thread so the UI never blocks on a model or a command.

The runtime is built *inside* the worker thread: its SQLite connections (checkpoints, tool index,
facts) belong to the thread that uses them. Everything crosses threads as Qt signals.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping

from PySide6.QtCore import QObject, QThread, Signal, Slot

from assistant.bootstrap import Runtime
from assistant.domain import AssistantError, ErrorEvent, Event
from assistant.service import friendly_error

log = logging.getLogger(__name__)


class AssistantWorker(QObject):
    ready = Signal(int)  # runtime is up; payload = number of available tools
    failed = Signal(str)  # runtime could not start
    history = Signal(object)  # list[Turn] of the resumed session
    emitted = Signal(object)  # one service Event
    closed = Signal()

    def __init__(self, factory: Callable[[], Runtime], session: str) -> None:
        super().__init__()
        self._factory = factory
        self._session = session
        self._runtime: Runtime | None = None

    @Slot()
    def start(self) -> None:
        try:
            runtime = self._factory()
        except AssistantError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            log.exception("could not start the assistant")
            self.failed.emit(friendly_error(exc))
            return
        self._runtime = runtime
        runtime.start_warmup()  # load models while the user is still reading the greeting
        assistant = runtime.assistant
        self.history.emit(assistant.history(self._session))
        self.ready.emit(len(runtime.registry))
        pending = assistant.pending_approval(self._session)
        if pending is not None:  # the app was closed while a tool call awaited approval
            self.emitted.emit(pending)

    @Slot(str)
    def send(self, text: str) -> None:
        if self._runtime is not None:
            self._pump(self._runtime.assistant.send(self._session, text))

    @Slot(object)
    def resume(self, decisions: Mapping[str, bool]) -> None:
        if self._runtime is not None:
            self._pump(self._runtime.assistant.resume(self._session, decisions))

    @Slot()
    def reset(self) -> None:
        if self._runtime is not None:
            self._runtime.assistant.reset(self._session)

    @Slot()
    def shutdown(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
            self._runtime = None
        self.closed.emit()
        thread = QThread.currentThread()
        if thread is not None:
            thread.quit()

    def _pump(self, events: Iterable[Event]) -> None:
        try:
            for event in events:
                self.emitted.emit(event)
        except Exception as exc:  # the service reports its own failures; this is the last resort
            log.exception("turn failed")
            self.emitted.emit(ErrorEvent(message=friendly_error(exc)))
