"""The chat popup that opens next to the pet: bubbles, tool activity and approval cards."""

from __future__ import annotations

import re
from collections.abc import Iterable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

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
from assistant.ui.formatting import TableOutput, TextOutput, parse_output
from assistant.ui.state import STATUS_TEXT, Mood

CHAT_SIZE = (380, 540)
_OUTPUT_LIMIT = 4000  # characters of tool output kept in a step card

_ORIGINAL_PREFIX = re.compile(r"Original output of ([^\n:]+):\n\n")  # see domain.original

_RISK_COLOR = {
    RiskLevel.READ_ONLY: "#5be37d",
    RiskLevel.MUTATING: "#ffc247",
    RiskLevel.DESTRUCTIVE: "#ff5b5b",
}
_STATUS_ICON = {"ok": "✓", "error": "✗", "timeout": "⏱", "denied": "⊘"}

_STYLE = """
#card { background: #1b2033; border: 1px solid #323a58; border-radius: 16px; }
#header { background: #232a45; border-top-left-radius: 16px; border-top-right-radius: 16px; }
#title { color: #f2f4ff; font-weight: 600; font-size: 14px; }
#status { color: #98a2c8; font-size: 11px; }
QScrollArea, #messages { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a4366; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
#user, #assistant, #error { border-radius: 12px; }
QTextBrowser { font-size: 13px; background: transparent; border: none; }
#user { background: #4a69d8; }
#user QTextBrowser { color: white; }
#assistant { background: #2a3150; }
#assistant QTextBrowser { color: #e8ebf7; }
#error { background: #4a2430; }
#error QTextBrowser { color: #ffb4bf; }
#toolcard { background: #202744; border: 1px solid #323a58; border-radius: 10px; }
#toolcard QLabel { color: #cdd3ee; font-size: 12px; }
#toolcommand { font-family: Consolas, 'Cascadia Mono', monospace; color: #8d97bd; font-size: 11px; }
#toolstate { color: #98a2c8; }
#toolstate[status="ok"] { color: #5be37d; }
#toolstate[status="error"], #toolstate[status="timeout"] { color: #ff7b7b; }
#toolstate[status="denied"] { color: #ffc247; }
QTextBrowser[mono="true"] { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 11px;
                            color: #cfe3ff; background: #161b2e; border-radius: 6px; }
#outtable { background: #161b2e; alternate-background-color: #1a2038; border: none;
            border-radius: 6px; color: #cfe3ff; font-size: 11px; }
#outtable QHeaderView::section { background: #232a45; color: #98a2c8; border: none;
                                 padding: 3px 8px; font-size: 11px; font-weight: 600; }
#outtable::item { padding: 0 8px; }
#outtable::item:selected { background: #2f3a63; color: white; }
#caption { color: #98a2c8; font-size: 11px; }
#link { background: transparent; color: #7f9cff; padding: 0; font-size: 11px; }
#link:hover { color: #a9bcff; background: transparent; }
#activity { color: #98a2c8; font-size: 12px; font-style: italic; padding: 2px 4px; }
#approval { background: #262d49; border: 1px solid #4a5483; border-radius: 12px; }
#approval QLabel { color: #e8ebf7; font-size: 12px; }
#command { font-family: Consolas, 'Cascadia Mono', monospace; color: #cfe3ff;
           background: #161b2e; border-radius: 6px; padding: 6px; }
#warning { color: #ffc247; }
QLineEdit { background: #11162a; color: #f2f4ff; border: 1px solid #323a58;
            border-radius: 10px; padding: 8px 10px; font-size: 13px; }
QLineEdit:focus { border-color: #4a69d8; }
QLineEdit:disabled { color: #6c7599; }
QPushButton { background: #2f3a63; color: #f2f4ff; border: none; border-radius: 10px;
              padding: 7px 14px; font-size: 12px; }
QPushButton:hover { background: #3b4880; }
QPushButton:disabled { background: #232a45; color: #5f688d; }
#primary { background: #4a69d8; }
#primary:hover { background: #5a78e6; }
#danger { background: #7a2e3b; }
#danger:hover { background: #94384a; }
#close { background: transparent; color: #98a2c8; padding: 2px 8px; font-size: 16px; }
#close:hover { color: white; background: #3b4880; }
"""


class _MessageScroll(QScrollArea):
    """Keeps the message column exactly as wide as the viewport so wrapped text never overflows."""

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        widget = self.widget()
        if widget is not None:
            widget.setFixedWidth(self.viewport().width())


class _AutoText(QTextBrowser):
    """Read-only rich text that grows to fit its content (no inner scrolling).

    Used instead of a wrapped QLabel: Qt computes a QLabel's Markdown height-for-width badly, which
    can leave a bubble thousands of pixels tall and the chat looking empty.
    """

    MONO_MAX_HEIGHT = 280  # long tool output scrolls inside its box instead of taking over the chat

    def __init__(self, *, mono: bool = False) -> None:
        super().__init__()
        self._max_height = self.MONO_MAX_HEIGHT if mono else None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if mono else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Selectable but never navigable: model output must not be able to open links or files.
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().setDocumentMargin(6 if mono else 0)  # padding lives in the document
        self.setProperty("mono", mono)
        self.viewport().setAutoFillBackground(False)
        self.document().documentLayout().documentSizeChanged.connect(lambda _size: self._fit())
        self._fit()

    def _fit(self) -> None:
        height = int(self.document().size().height()) + 2
        self.setFixedHeight(min(height, self._max_height) if self._max_height else height)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
        self._fit()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.verticalScrollBar().maximum() > 0:
            super().wheelEvent(event)  # a long output scrolls inside its own box
        else:
            event.ignore()  # nothing to scroll here: let the chat scroll

    def loadResource(self, _type: int, _name: object) -> None:  # noqa: N802
        return None  # never fetch images or files named by model output


class _Bubble(QFrame):
    """A message. Assistant text is Markdown; everything else is shown literally."""

    def __init__(self, role: str, text: str = "") -> None:
        super().__init__()
        self.setObjectName(role)
        self.role = role
        self._markdown = role == "assistant"
        self._text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 8, 11, 8)
        self._view = _AutoText()
        layout.addWidget(self._view)
        self._column = layout
        self.append(text)

    def append(self, text: str) -> None:
        self._text += text
        if self._markdown:
            self._view.setMarkdown(self._text)
        else:
            self._view.setPlainText(self._text)

    def finalize(self) -> None:
        """Called when the reply is complete: show raw tool output as a table / JSON / monospace.

        The assistant sometimes sends a tool's output verbatim (short results shown as they are, or
        "Original output of <tool>:"). Markdown would collapse its line breaks and turn the dashes
        under a header into a rule, so such messages get the same views as a tool card instead.
        """
        if not self._markdown:
            return
        text = self._text.strip()
        match = _ORIGINAL_PREFIX.match(text)
        body = text[match.end() :] if match else text
        parsed = parse_output(body)
        structured = isinstance(parsed, TableOutput) or (
            isinstance(parsed, TextOutput) and parsed.kind == "json"
        )
        if not structured and match is None:
            return
        layout = self._column
        layout.removeWidget(self._view)
        self._view.deleteLater()
        if match is not None:
            caption = QLabel(f"Original output of {match.group(1)}")
            caption.setObjectName("caption")
            layout.addWidget(caption)
        layout.addWidget(_build_output(body, limit=None))
        copy = QPushButton("Copy")
        copy.setObjectName("link")
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(body))
        layout.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)

    @property
    def text_content(self) -> str:
        return self._text

    def openExternalLinks(self) -> bool:  # noqa: N802
        return self._view.openExternalLinks()


class _Activity(QLabel):
    """Animated "Thinking..." line, the GUI's version of the terminal spinner."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activity")
        self._label = "Thinking"
        self._dots = 0
        self._timer = QTimer(self)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._tick)

    def run(self, label: str) -> None:
        self._label = label
        self._dots = 0
        self._tick()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self.setText(f"{self._label}{'.' * (self._dots % 4)}")
        self._dots += 1


class _ToolRow(QFrame):
    """One tool step, like the terminal's `-> tool (risk) command` / `ok tool - ms` lines."""

    def __init__(self, event: ToolProposedEvent) -> None:
        super().__init__()
        self.setObjectName("toolcard")
        self.status: str | None = None
        color = _RISK_COLOR[event.risk]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)

        top = QHBoxLayout()
        title = QLabel(
            f"<b>{_escape(event.tool)}</b> <span style='color:{color}'>{event.risk.value}</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        self._state = QLabel("running\u2026")
        self._state.setObjectName("toolstate")
        top.addWidget(title, 1)
        top.addWidget(self._state)
        layout.addLayout(top)

        command = QLabel(event.command)
        command.setObjectName("toolcommand")
        command.setWordWrap(True)
        command.setTextFormat(Qt.TextFormat.PlainText)
        command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(command)

        links = QHBoxLayout()
        self._toggle = QPushButton("Show output")
        self._copy = QPushButton("Copy")
        for button in (self._toggle, self._copy):
            button.setObjectName("link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.hide()
            links.addWidget(button)
        links.addStretch(1)
        self._toggle.clicked.connect(self._flip)
        self._copy.clicked.connect(self._copy_output)
        layout.addLayout(links)
        self._raw = ""
        self._output: QWidget | None = None
        self._layout = layout

    def finish(self, event: ToolResultEvent) -> None:
        self.status = event.status
        icon = _STATUS_ICON.get(event.status, "?")
        self._state.setText(f"{icon} {event.duration_ms} ms")
        self._state.setProperty("status", event.status)
        self._state.style().unpolish(self._state)
        self._state.style().polish(self._state)
        text = event.output.strip()
        if text:
            self._raw = text
            self._output = _build_output(text)
            self._output.hide()
            self._layout.addWidget(self._output)
            self._toggle.show()
            self._copy.show()
            if event.status != "ok":  # failures are shown straight away, like the terminal
                self._flip()

    def _flip(self) -> None:
        if self._output is None:
            return
        show = self._output.isHidden()
        self._output.setVisible(show)
        self._toggle.setText("Hide output" if show else "Show output")

    def _copy_output(self) -> None:
        QGuiApplication.clipboard().setText(self._raw)
        self._copy.setText("Copied")
        QTimer.singleShot(1500, lambda: self._copy.setText("Copy"))


class _OutputTable(QTableWidget):
    """A tool's tabular output as a real table: numbers right-aligned, header pinned."""

    ROW_HEIGHT = 24
    MAX_VISIBLE_ROWS = 8

    def __init__(self, table: TableOutput) -> None:
        super().__init__(len(table.rows), len(table.headers))
        self.setObjectName("outtable")
        self.setHorizontalHeaderLabels(table.headers)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        numeric = table.numeric
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(cell)
                if numeric[c]:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.setItem(r, c, item)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(not numeric[-1])  # a stretched number column looks adrift
        for c, is_number in enumerate(numeric):
            head = self.horizontalHeaderItem(c)
            if head is not None and is_number:
                head.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        shown = min(len(table.rows), self.MAX_VISIBLE_ROWS)
        scrollbar = self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(header.sizeHint().height() + shown * self.ROW_HEIGHT + scrollbar + 4)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.verticalScrollBar().maximum() == 0:
            event.ignore()  # nothing to scroll here: let the chat scroll
        else:
            super().wheelEvent(event)


def _build_output(text: str, limit: int | None = _OUTPUT_LIMIT) -> QWidget:
    """Pick the best view for a tool's output (see ``formatting`` for the schema)."""
    parsed = parse_output(text)
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(3)
    if isinstance(parsed, TableOutput):
        column.addWidget(_OutputTable(parsed))
        if parsed.hidden_rows:
            more = QLabel(f"\u2026 and {parsed.hidden_rows} more rows (use Copy for everything)")
            more.setObjectName("toolstate")
            column.addWidget(more)
        return box
    shown = parsed.text
    if limit is not None and len(shown) > limit:
        shown = shown[:limit] + "\n\u2026 (truncated, use Copy for everything)"
    view = _AutoText(mono=True)
    view.setPlainText(shown)
    column.addWidget(view)
    return box


class _ApprovalCard(QFrame):
    """Shows the exact command a tool wants to run and waits for Approve or Deny."""

    decided = Signal(str, bool)  # call_id, approved

    def __init__(self, request: ApprovalRequest) -> None:
        super().__init__()
        self.setObjectName("approval")
        self._request = request
        self._confirm = request.mode is ApprovalMode.CONFIRM
        color = _RISK_COLOR[request.risk]
        self.setStyleSheet(f"#approval {{ border-color: {color}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title = QLabel(
            f"<b>{_escape(request.tool)}</b> "
            f"<span style='color:{color}'>{request.risk.value}</span> wants to run:"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        command = QLabel(request.command)
        command.setObjectName("command")
        command.setWordWrap(True)
        command.setTextFormat(Qt.TextFormat.PlainText)
        command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(command)

        if request.message:
            warning = QLabel(request.message)
            warning.setObjectName("warning")
            warning.setWordWrap(True)
            warning.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(warning)

        self._typed: QLineEdit | None = None
        if self._confirm:
            self._typed = QLineEdit()
            self._typed.setPlaceholderText(f"Type “{request.tool}” to allow")
            self._typed.textChanged.connect(self._refresh)
            layout.addWidget(self._typed)

        buttons = QHBoxLayout()
        self._deny = QPushButton("Deny")
        self._deny.setObjectName("danger")
        self._allow = QPushButton("Approve")
        self._allow.setObjectName("primary")
        self._deny.clicked.connect(lambda: self._decide(False))
        self._allow.clicked.connect(lambda: self._decide(True))
        buttons.addStretch(1)
        buttons.addWidget(self._deny)
        buttons.addWidget(self._allow)
        layout.addLayout(buttons)
        self._result = QLabel()
        self._result.hide()
        layout.addWidget(self._result)
        self._refresh()

    @property
    def call_id(self) -> str:
        return self._request.call_id

    def deny(self) -> None:
        if self._deny.isEnabled():
            self._decide(False)

    def focus_default(self) -> None:
        # Deny is the default action: Enter must never approve something by accident.
        (self._typed or self._deny).setFocus()

    def _refresh(self) -> None:
        if self._typed is not None:
            self._allow.setEnabled(self._typed.text().strip() == self._request.tool)

    def _decide(self, approved: bool) -> None:
        for widget in (self._allow, self._deny, self._typed):
            if widget is not None:
                widget.hide()
        self._result.setText("Approved ✓" if approved else "Denied ⊘")
        self._result.show()
        self.decided.emit(self._request.call_id, approved)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ChatWindow(QWidget):
    message_submitted = Signal(str)
    decisions_made = Signal(object)  # {call_id: bool}
    reset_requested = Signal()
    hidden_by_user = Signal()
    settings_requested = Signal()

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self._bubble: _Bubble | None = None
        self._tools: dict[str, _ToolRow] = {}
        self._cards: dict[str, _ApprovalCard] = {}
        self._decisions: dict[str, bool] = {}
        self._busy = False
        self._ready = False
        self._stick = True
        self._closing = False
        self._auto_scrolling = False
        self._activity = _Activity()
        self._activity_shown = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)
        self.resize(*CHAT_SIZE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        outer.addWidget(card)
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        column.addWidget(self._build_header())
        self._scroll = _MessageScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._messages = QWidget()
        self._messages.setObjectName("messages")
        self._list = QVBoxLayout(self._messages)
        self._list.setContentsMargins(12, 12, 12, 12)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        self._scroll.setWidget(self._messages)
        column.addWidget(self._scroll, 1)
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._on_range_changed)
        bar.valueChanged.connect(self._on_scrolled)
        # The window fades in and out; the message list glides to the newest message.
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(140)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)
        self._glide = QPropertyAnimation(bar, b"value", self)
        self._glide.setDuration(180)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.finished.connect(lambda: setattr(self, "_auto_scrolling", False))

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 8, 12, 12)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Starting up…")
        self._input.returnPressed.connect(self._submit)
        send = QPushButton("Send")
        send.setObjectName("primary")
        send.clicked.connect(self._submit)
        self._send = send
        footer.addWidget(self._input, 1)
        footer.addWidget(send)
        column.addLayout(footer)

        self._update_enabled()
        self.add_note("Hi! Ask me something, or tell me what to do on this PC.")

    # -- header ------------------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 8, 10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(self._name)
        title.setObjectName("title")
        self._status = QLabel("Starting up…")
        self._status.setObjectName("status")
        titles.addWidget(title)
        titles.addWidget(self._status)
        row.addLayout(titles, 1)
        gear = QPushButton("Settings")
        gear.setObjectName("link")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setToolTip("Open settings")
        gear.clicked.connect(self.settings_requested)
        row.addWidget(gear)
        close = QPushButton("✕")
        close.setObjectName("close")
        close.setToolTip("Hide the chat (the pet stays)")
        close.clicked.connect(self.hide_chat)
        row.addWidget(close)
        return header

    # -- state from the app ------------------------------------------------------------------

    def set_ready(self, tool_count: int) -> None:
        self._ready = True
        self._input.setPlaceholderText("Type a message…")
        self._update_enabled()
        self.set_mood(Mood.IDLE)
        self._status.setToolTip(f"{tool_count} tools available on this PC")

    def set_loading(self, text: str) -> None:
        """The assistant is restarting (new settings): no input until it is ready again."""
        self._ready = False
        self._input.setPlaceholderText(text)
        self._status.setText(text)
        self._update_enabled()

    def set_failed(self, message: str) -> None:
        self.add_error(message)
        self._input.setPlaceholderText("The assistant could not start")
        self.set_mood(Mood.ERROR)

    def set_mood(self, mood: Mood) -> None:
        if not self._ready and mood is Mood.IDLE:
            return
        self._status.setText(STATUS_TEXT[mood])

    def show_history(self, turns: Iterable[object]) -> None:
        for turn in turns:
            role, text = getattr(turn, "role", ""), getattr(turn, "text", "")
            if text:
                bubble = _Bubble("user" if role == "user" else "assistant", text)
                self._add(bubble)
                bubble.finalize()

    # -- events ------------------------------------------------------------------------------

    def handle_event(self, event: Event) -> None:
        if isinstance(event, TokenEvent):
            if self._bubble is None:
                self._bubble = _Bubble("assistant")
                self._add(self._bubble)
            self._bubble.append(event.text)
            self._hide_activity()
        elif isinstance(event, ToolProposedEvent):
            self._bubble = None  # text after a tool starts a new bubble
            row = _ToolRow(event)
            self._tools[event.call_id] = row
            self._add(row)
            self._show_activity(f"Running {event.tool}")
        elif isinstance(event, ToolResultEvent):
            self._on_tool_result(event)
            self._show_activity("Thinking")
        elif isinstance(event, ApprovalRequestedEvent):
            self._bubble = None
            self._hide_activity()
            self._ask(event)
        elif isinstance(event, FinalEvent):
            self._hide_activity()
            if self._bubble is None and event.text:
                self._bubble = _Bubble("assistant", event.text)
                self._add(self._bubble)
            if self._bubble is not None:
                self._bubble.finalize()
            self._bubble = None
            self._finish_turn()
        elif isinstance(event, ErrorEvent):
            self._hide_activity()
            self.add_error(event.message)
            self._bubble = None
            self._finish_turn()

    def _on_tool_result(self, event: ToolResultEvent) -> None:
        row = self._tools.get(event.call_id)
        if row is not None:
            row.finish(event)

    def add_note(self, text: str) -> None:
        self._add(_Bubble("assistant", text))

    def add_error(self, text: str) -> None:
        self._add(_Bubble("error", text))

    def clear(self) -> None:
        self._hide_activity()
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._bubble = None
        self._tools.clear()
        self._cards.clear()
        self._decisions.clear()
        self._busy = False
        self._update_enabled()

    # -- approvals ---------------------------------------------------------------------------

    def _ask(self, event: ApprovalRequestedEvent) -> None:
        self._decisions = {}
        self._cards = {}
        for request in event.requests:
            card = _ApprovalCard(request)
            card.decided.connect(self._on_decided)
            self._cards[request.call_id] = card
            self._add(card)
        if self._cards:
            next(iter(self._cards.values())).focus_default()

    def _on_decided(self, call_id: str, approved: bool) -> None:
        self._decisions[call_id] = approved
        if len(self._decisions) == len(self._cards):
            decisions, self._decisions, self._cards = self._decisions, {}, {}
            self.decisions_made.emit(decisions)

    def deny_open_cards(self) -> None:
        for card in list(self._cards.values()):
            card.deny()

    # -- input -------------------------------------------------------------------------------

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text or self._busy or not self._ready:
            return
        self._input.clear()
        self._add(_Bubble("user", text))
        self._bubble = None
        self._busy = True
        self._update_enabled()
        self._show_activity("Thinking")
        self.message_submitted.emit(text)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def begin_busy(self) -> None:
        """A turn was started elsewhere (e.g. an approval was just answered)."""
        self._busy = True
        self._update_enabled()
        self._show_activity("Thinking")

    def _finish_turn(self) -> None:
        self._busy = False
        self._update_enabled()
        if self.isVisible():
            self._input.setFocus()

    def _update_enabled(self) -> None:
        enabled = self._ready and not self._busy
        self._input.setEnabled(enabled)
        self._send.setEnabled(enabled)

    # -- layout / placement ------------------------------------------------------------------

    def _add(self, widget: QWidget) -> None:
        container = widget
        if isinstance(widget, _Bubble):  # keep a margin on the far side, like a messenger
            container = QWidget()
            row = QHBoxLayout(container)
            far, near = (36, 0) if widget.role == "user" else (0, 36)
            row.setContentsMargins(far, 0, near, 0)
            row.addWidget(widget)
        tail = 2 if self._activity_shown else 1  # the activity line always stays last
        self._list.insertWidget(self._list.count() - tail, container)

    def _show_activity(self, label: str) -> None:
        if self._activity_shown:
            self._list.removeWidget(self._activity)
        self._list.insertWidget(self._list.count() - 1, self._activity)
        self._activity_shown = True
        self._activity.show()
        self._activity.run(label)

    def _hide_activity(self) -> None:
        if self._activity_shown:
            self._list.removeWidget(self._activity)
            self._activity.stop()
            self._activity.hide()
            self._activity_shown = False

    def _on_scrolled(self, value: int) -> None:
        if not self._auto_scrolling:  # only the user's own scrolling decides whether to follow
            self._stick = value >= self._scroll.verticalScrollBar().maximum() - 6

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        if not self._stick:
            return
        bar = self._scroll.verticalScrollBar()
        if not self.isVisible() or abs(maximum - bar.value()) > 600:
            self._glide.stop()
            self._auto_scrolling = False
            bar.setValue(maximum)  # nothing to see: jump
            return
        self._auto_scrolling = True
        self._glide.stop()
        self._glide.setStartValue(bar.value())
        self._glide.setEndValue(maximum)
        self._glide.start()

    def anchor_to(self, pet: QRect) -> None:
        """Place the window beside the pet, on whichever side has room, inside the screen."""
        screen = QGuiApplication.screenAt(pet.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        width, height = self.width(), self.height()
        x = pet.right() - width if pet.center().x() > area.center().x() else pet.left()
        y = pet.top() - height - 6
        if y < area.top():
            y = pet.bottom() + 6
        x = max(area.left() + 4, min(x, area.right() - width - 4))
        y = max(area.top() + 4, min(y, area.bottom() - height - 4))
        self.move(QPoint(x, y))

    @property
    def is_open(self) -> bool:
        """Visible and not on its way out."""
        return self.isVisible() and not self._closing

    def present(self, pet: QRect) -> None:
        self.anchor_to(pet)
        self._closing = False
        self._fade.stop()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
        self.show()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self.raise_()
        self.activateWindow()
        self._stick = True
        self._on_range_changed(0, self._scroll.verticalScrollBar().maximum())
        if self._input.isEnabled():
            QTimer.singleShot(0, self._input.setFocus)

    def hide_chat(self) -> None:
        if not self.isVisible():
            self.hidden_by_user.emit()
            return
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._closing:
            self._closing = False
            self.hide()
            self.setWindowOpacity(1.0)
            self.hidden_by_user.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide_chat()
        else:
            super().keyPressEvent(event)
