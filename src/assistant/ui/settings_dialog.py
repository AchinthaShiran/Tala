"""The settings window: plain-language controls over ``config.yaml``.

Every control is bound to one or more dotted settings paths. Saving writes only what the user
changed (see ``ConfigStore``); the assistant is then restarted by the app so the change applies.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import ollama
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from assistant.bootstrap import pack_roots
from assistant.config import AppPaths, Settings
from assistant.domain import ConfigError, RiskLevel, ToolSpec, current_platform
from assistant.domain.branding import APP_NAME, SETTINGS_ENV_PREFIX
from assistant.memory import FactStore
from assistant.packs import ToolRegistry, load_packs
from assistant.setup import (
    Hardware,
    detect_hardware,
    installed_tags,
    load_catalog,
    missing_tags,
    pull_model,
    recommend,
)
from assistant.setup.planner import model_memory_gb
from assistant.ui.characters import CharacterError, discover, load_character
from assistant.ui.config_store import ConfigStore, dig
from assistant.ui.pet import DEFAULT_SIZE, PET_SIZES, render_icon, write_example_character
from assistant.ui.theme import STYLE
from assistant.ui.vector_characters import CHARACTERS, ROBOT

_APPROVAL_LABELS = {
    "auto": "Run automatically",
    "ask": "Ask me first",
    "confirm": "Ask me, and I type the tool name",
    "deny": "Never allow",
}
_RISK_COLOR = {"read_only": "#5be37d", "mutating": "#ffc247", "destructive": "#ff7b7b"}
_RISK_TEXT = {"read_only": "reads only", "mutating": "changes things", "destructive": "destructive"}
_DIRECT_OUTPUT_CHARS = 600  # "show short results as they are" threshold


@dataclass
class _Bind:
    """One control and the settings path(s) it writes."""

    paths: tuple[str, ...]
    read: Callable[[], Any]
    initial: Any


class _Job(QThread):
    """Runs a blocking function (a network call) off the UI thread."""

    result = Signal(object)
    error = Signal(str)
    progress = Signal(str, int)  # message, percent (-1 when unknown)

    def __init__(self, fn: Callable[[_Job], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.cancelled = False

    def run(self) -> None:
        try:
            self.result.emit(self._fn(self))
        except Exception as exc:
            self.error.emit(str(exc) or type(exc).__name__)


class SettingsDialog(QDialog):
    saved = Signal()  # the file changed: restart the assistant
    character_selected = Signal(str)  # folder name of a character pack, "" = built-in robot
    size_selected = Signal(int)  # pet window size in pixels
    new_conversation_requested = Signal()

    def __init__(
        self,
        store: ConfigStore,
        paths: AppPaths,
        *,
        auto_check: bool = True,
        current_character: str = "",
        current_size: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_character = current_character
        self._initial_size = current_size
        self._store = store
        self._paths = paths
        self._auto_check = auto_check
        self._settings: Settings = store.load()
        self._dump: dict[str, Any] = self._settings.model_dump(mode="json")
        self._binds: list[_Bind] = []
        self._jobs: list[_Job] = []
        self._installed: set[str] | None = None
        self._catalog = load_catalog()
        self._facts = FactStore(paths.facts_db)

        self.setWindowTitle(f"{APP_NAME} settings")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(STYLE)
        self.resize(800, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        title = _label("Settings", "title")
        root.addWidget(title)
        root.addWidget(
            _label("Changes apply when you press Save; the assistant restarts by itself.", "help")
        )

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)
        for name, build in (
            ("Models", self._models_tab),
            ("Model library", self._library_tab),
            ("Behaviour", self._behaviour_tab),
            ("Safety", self._safety_tab),
            ("Tools", self._tools_tab),
            ("Memory", self._memory_tab),
            ("Pet", self._pet_tab),
            ("Advanced", self._advanced_tab),
        ):
            self._tabs.addTab(build(), name)

        self._error = _label("", "bad")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setProperty("primary", True)
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._refresh_model_status()
        if auto_check:
            self._check_connection()

    # -- building blocks ---------------------------------------------------------------------

    def _value(self, path: str, default: Any = None) -> Any:
        return dig(self._dump, path, default)

    def _bind(self, paths: tuple[str, ...], read: Callable[[], Any]) -> None:
        self._binds.append(_Bind(paths, read, read()))  # initial = what the widget shows now

    def _form(self, host: QWidget) -> QFormLayout:
        form = QFormLayout(host)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        return form

    def _row(self, form: QFormLayout, text: str, widget: QWidget, help_text: str = "") -> None:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(widget)
        if help_text:
            hint = _label(help_text, "help")
            hint.setWordWrap(True)
            column.addWidget(hint)
        form.addRow(QLabel(text), box)

    def _checkbox(
        self, paths: tuple[str, ...], text: str, *, checked: bool | None = None
    ) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self._value(paths[0]) if checked is None else checked))
        self._bind(paths, box.isChecked)
        return box

    def _spin(
        self,
        paths: tuple[str, ...],
        low: int,
        high: int,
        *,
        step: int = 1,
        suffix: str = "",
        no_limit: bool = False,
        special: str = "No limit",
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0 if no_limit else low, high)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        if no_limit:
            spin.setSpecialValueText(special)
        spin.setValue(int(self._value(paths[0], 0) or 0))
        self._bind(paths, lambda: (spin.value() or None) if no_limit else spin.value())
        return spin

    def _decimal(
        self, paths: tuple[str, ...], low: float, high: float, step: float
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.setValue(float(self._value(paths[0], 0.0)))
        self._bind(paths, lambda: round(spin.value(), 2))
        return spin

    def _choice(
        self, paths: tuple[str, ...], options: list[tuple[str, str]], current: Any
    ) -> QComboBox:
        combo = QComboBox()
        for value, text in options:
            combo.addItem(text, value)
        index = combo.findData(current)
        combo.setCurrentIndex(max(index, 0))
        self._bind(paths, combo.currentData)
        return combo

    def _text(self, paths: tuple[str, ...]) -> QLineEdit:
        edit = QLineEdit(str(self._value(paths[0], "")))
        self._bind(paths, lambda: edit.text().strip())
        return edit

    def _model_combo(
        self, paths: tuple[str, ...], suggestions: list[str], default: str
    ) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        current = str(self._value(paths[0], default))
        combo.addItems(list(dict.fromkeys([current, *suggestions])))
        combo.setCurrentText(current)
        self._bind(paths, lambda: combo.currentText().strip())
        combo.currentTextChanged.connect(lambda _t: self._refresh_model_status())
        return combo

    # -- tab: models -------------------------------------------------------------------------

    def _models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        connection = QGroupBox("Ollama (the program that runs the language models)")
        form = self._form(connection)
        self._url = self._text(
            ("models.main.base_url", "models.router.base_url", "embeddings.base_url")
        )
        check = QPushButton("Check")
        check.clicked.connect(self._check_connection)
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._url, 1)
        row.addWidget(check)
        self._row(
            form, "Address", line, "Usually http://localhost:11434 (Ollama running on this PC)."
        )
        self._connection = _label("", "help")
        form.addRow("", self._connection)
        layout.addWidget(connection)

        models = QGroupBox("Models")
        form = self._form(models)
        chat = [m.tag for m in self._catalog.chat_models()]
        self._main = self._model_combo(("models.main.name",), chat, "gemma4:e2b")
        self._main_status = _label("", "help")
        self._row(
            form,
            "Main model",
            self._main,
            "Answers you and drives the tools. Bigger is smarter but slower.",
        )
        form.addRow("", self._main_status)
        self._router = self._model_combo(
            ("models.router.name",), [m.tag for m in self._catalog.router_models()], "granite4.1:3b"
        )
        self._router_status = _label("", "help")
        self._row(
            form,
            "Quick-decision model",
            self._router,
            "A small, fast model that decides whether a request needs a tool.",
        )
        form.addRow("", self._router_status)
        self._ctx = self._spin(("models.main.num_ctx",), 1024, 131072, step=1024, suffix=" tokens")
        self._row(
            form,
            "Memory per conversation",
            self._ctx,
            "How much of the conversation the model can see. Larger uses more RAM and is slower on a CPU.",
        )
        current_keep = str(self._value("models.main.keep_alive", "30m"))
        keep_options = [
            ("5m", "5 minutes"),
            ("30m", "30 minutes"),
            ("2h", "2 hours"),
            ("24h", "All day (24 hours)"),
        ]
        if current_keep not in {v for v, _t in keep_options}:
            keep_options.append((current_keep, current_keep))
        self._keep_alive = self._choice(
            ("models.main.keep_alive", "models.router.keep_alive"), keep_options, current_keep
        )
        self._row(
            form,
            "Keep models loaded for",
            self._keep_alive,
            "Loading a model is slow on a CPU. Longer keeps answers quick but holds RAM.",
        )
        layout.addWidget(models)

        search = QGroupBox("Finding the right tool")
        form = self._form(search)
        self._use_embeddings = self._checkbox(
            ("retrieval.use_embeddings",), "Use meaning-based search (embeddings)"
        )
        self._embedding = self._model_combo(
            ("embeddings.name",),
            [m.tag for m in self._catalog.embedding_models()],
            "nomic-embed-text",
        )
        self._embedding_status = _label("", "help")
        form.addRow(self._use_embeddings)
        self._use_embeddings.toggled.connect(lambda _c: self._refresh_model_status())
        self._row(
            form,
            "Embedding model",
            self._embedding,
            "Without it, tools are found by keywords only.",
        )
        form.addRow("", self._embedding_status)
        layout.addWidget(search)

        self._download = QPushButton("Download missing models")
        self._download.setProperty("primary", True)
        self._download.clicked.connect(self._download_missing)
        self._download.hide()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        self._progress_text = _label("", "help")
        layout.addWidget(self._download)
        layout.addWidget(self._progress)
        layout.addWidget(self._progress_text)
        layout.addStretch(1)
        return page

    def _start_job(self, fn: Callable[[_Job], Any]) -> _Job:
        job = _Job(fn)
        self._jobs.append(job)
        job.finished.connect(lambda j=job: self._jobs.remove(j) if j in self._jobs else None)
        return job

    def _check_connection(self) -> None:
        host = self._url.text().strip() or "http://localhost:11434"
        _say(self._connection, "Checking…", "help")

        def fetch(_job: _Job) -> set[str]:
            return installed_tags(ollama.Client(host=host, timeout=4.0))

        job = self._start_job(fetch)
        job.result.connect(self._on_installed)
        job.error.connect(self._on_unreachable)
        job.start()

    def _on_installed(self, tags: object) -> None:
        self._installed = set(tags) if isinstance(tags, set) else set()
        _say(self._connection, f"Connected. {len(self._installed)} models installed.", "ok")
        self._refresh_model_status()

    def _on_unreachable(self, message: str) -> None:
        self._installed = None
        _say(
            self._connection,
            "Can't reach Ollama. Is it installed and running? (https://ollama.com/download)",
            "bad",
        )
        self._connection.setToolTip(message)
        self._refresh_model_status()

    def _wanted_models(self) -> list[str]:
        wanted = [self._main.currentText().strip(), self._router.currentText().strip()]
        if self._use_embeddings.isChecked():
            wanted.append(self._embedding.currentText().strip())
        return [w for w in dict.fromkeys(wanted) if w]

    def _refresh_model_status(self) -> None:
        for combo, label in (
            (self._main, self._main_status),
            (self._router, self._router_status),
            (self._embedding, self._embedding_status),
        ):
            tag = combo.currentText().strip()
            if self._installed is None or not tag:
                _say(label, "", "help")
            elif missing_tags([tag], self._installed):
                _say(label, "Not downloaded yet.", "warn")
            else:
                _say(label, "Downloaded.", "ok")
        self._embedding.setEnabled(self._use_embeddings.isChecked())
        self._download.setVisible(bool(self._missing()))
        self._refresh_library()

    def _missing(self) -> list[str]:
        if self._installed is None:
            return []
        return missing_tags(self._wanted_models(), self._installed)

    def _download_missing(self) -> None:
        self._pull(self._missing(), self._download, self._progress, self._progress_text)

    def _pull(self, tags: list[str], button: QPushButton, bar: QProgressBar, text: QLabel) -> None:
        """Download ``tags`` in the background, reporting into the given widgets."""
        host = self._url.text().strip() or "http://localhost:11434"
        if not tags:
            return
        button.setEnabled(False)
        bar.setValue(0)
        bar.show()

        def pull(job: _Job) -> None:
            client = ollama.Client(host=host, timeout=None)
            for tag in tags:

                def on_progress(
                    status: str, total: int | None, done: int | None, tag: str = tag
                ) -> None:
                    if job.cancelled:
                        raise RuntimeError("cancelled")
                    percent = int(100 * (done or 0) / total) if total else -1
                    job.progress.emit(f"{tag}: {status}", percent)

                pull_model(client, tag, on_progress)

        def finish(message: str, *, failed: bool = False) -> None:
            button.setEnabled(True)
            bar.hide()
            _say(text, message, "bad" if failed else "ok")
            self._check_connection()

        job = self._start_job(pull)

        def show_progress(message: str, percent: int) -> None:
            text.setText(message)
            if percent >= 0:
                bar.setValue(percent)

        job.progress.connect(show_progress)
        job.result.connect(lambda _r: finish("Download finished."))
        job.error.connect(lambda m: finish(f"Download failed: {m}", failed=True))
        job.start()

    # -- tab: model library ------------------------------------------------------------------

    _SPEED: ClassVar[tuple[tuple[float, str], ...]] = (
        (3.0, "Very fast"),
        (6.0, "Fast"),
        (8.0, "Moderate"),
        (1e9, "Slower"),
    )
    _QUALITY: ClassVar[dict[str, str]] = {"light": "Good", "balanced": "Better", "heavy": "Best"}

    def _library_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = _label(
            "Models you can install. Smaller models answer faster; larger ones handle harder "
            "requests and make fewer mistakes with tools. For quick, good answers on most PCs "
            "start with a “Fast” model.",
            "help",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._pc_line = _label("Looking at this PC…", "help")
        self._pc_line.setWordWrap(True)
        layout.addWidget(self._pc_line)

        self._hardware: Hardware | None = None
        self._recommended_tag = ""
        entries = self._catalog.chat_models() + self._catalog.embedding_models()
        self._library_entries = entries
        table = QTableWidget(len(entries), 6)
        table.setHorizontalHeaderLabels(
            ["Model", "Speed", "Quality", "Download", "Memory", "Status"]
        )
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(34)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        table.itemSelectionChanged.connect(self._on_library_selection)
        self._library = table
        layout.addWidget(table, 1)

        self._library_note = _label("", "help")
        self._library_note.setWordWrap(True)
        layout.addWidget(self._library_note)

        buttons = QHBoxLayout()
        self._lib_main = QPushButton("Use as main model")
        self._lib_main.clicked.connect(lambda: self._use_selected(self._main))
        self._lib_router = QPushButton("Use for quick decisions")
        self._lib_router.clicked.connect(lambda: self._use_selected(self._router))
        self._lib_install = QPushButton("Download")
        self._lib_install.setProperty("primary", True)
        self._lib_install.clicked.connect(self._install_selected)
        for b in (self._lib_main, self._lib_router, self._lib_install):
            b.setEnabled(False)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._lib_progress = QProgressBar()
        self._lib_progress.setRange(0, 100)
        self._lib_progress.hide()
        self._lib_text = _label("", "help")
        layout.addWidget(self._lib_progress)
        layout.addWidget(self._lib_text)

        self._fill_library()
        if self._auto_check:
            self._detect_pc()
        return page

    def _speed_of(self, memory_gb: float) -> str:
        return next(text for limit, text in self._SPEED if memory_gb <= limit)

    def _fill_library(self) -> None:
        for row, entry in enumerate(self._library_entries):
            chat = entry.role == "chat"
            name = QTableWidgetItem(_title(entry))
            name.setToolTip(entry.notes)
            cells = [
                name,
                QTableWidgetItem(self._speed_of(entry.memory_gb) if chat else "—"),
                QTableWidgetItem(self._QUALITY[entry.tier] if chat else "Search"),
                QTableWidgetItem(f"{entry.download_gb:.1f} GB"),
                QTableWidgetItem(f"{entry.memory_gb:.1f} GB"),
                QTableWidgetItem(""),
            ]
            for col, item in enumerate(cells):
                item.setToolTip(entry.notes)
                self._library.setItem(row, col, item)
        self._refresh_library()

    def _refresh_library(self) -> None:
        table = getattr(self, "_library", None)
        if table is None:
            return
        budget = self._hardware.budget_gb if self._hardware else None
        ctx = int(self._value("models.main.num_ctx", 8192))
        for row, entry in enumerate(self._library_entries):
            status = table.item(row, 5)
            title = table.item(row, 0)
            if status is None or title is None:
                continue
            installed = (
                None if self._installed is None else not missing_tags([entry.tag], self._installed)
            )
            text, color = "—", "#8d97bd"
            if installed:
                text, color = "Installed", "#5be37d"
            elif installed is False:
                text, color = "Not installed", "#98a2c8"
            if entry.role == "chat" and budget is not None and model_memory_gb(entry, ctx) > budget:
                text, color = text + " · too big for this PC", "#ffc247"
            status.setText(text)
            status.setForeground(QColor(color))
            star = entry.tag == self._recommended_tag
            title.setText(("★ " if star else "") + _title(entry))
        self._on_library_selection()

    def _detect_pc(self) -> None:
        job = self._start_job(lambda _j: detect_hardware())
        job.result.connect(self._on_hardware)
        job.error.connect(lambda _m: _say(self._pc_line, "", "help"))
        job.start()

    def _on_hardware(self, hardware: object) -> None:
        if not isinstance(hardware, Hardware):
            return
        self._hardware = hardware
        choice = recommend(hardware, self._catalog).main
        self._recommended_tag = choice.tag
        self._pc_line.setText(
            f"This PC: {hardware.describe()}.  ★ Recommended for it: {choice.label} ({choice.tag})."
        )
        self._refresh_library()

    def _selected_entry(self) -> Any:
        rows = {i.row() for i in self._library.selectedIndexes()}
        return self._library_entries[min(rows)] if rows else None

    def _on_library_selection(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self._library_note.setText("Select a model to see details.")
            for b in (self._lib_main, self._lib_router, self._lib_install):
                b.setEnabled(False)
            return
        self._library_note.setText(entry.notes)
        chat = entry.role == "chat"
        installed = self._installed is not None and not missing_tags([entry.tag], self._installed)
        self._lib_main.setEnabled(chat)
        self._lib_router.setEnabled(chat and entry.router_ok)
        self._lib_install.setEnabled(not installed and self._installed is not None)
        self._lib_install.setText(f"Download ({entry.download_gb:.1f} GB)")
        self._lib_install.setToolTip(
            "" if self._installed is not None else "Check the Ollama connection first."
        )

    def _use_selected(self, combo: QComboBox) -> None:
        entry = self._selected_entry()
        if entry is not None:
            combo.setCurrentText(entry.tag)
            _say(
                self._lib_text,
                f"{entry.label} selected. Press Save to apply (Models tab shows the choice).",
                "ok",
            )

    def _install_selected(self) -> None:
        entry = self._selected_entry()
        if entry is not None:
            self._pull([entry.tag], self._lib_install, self._lib_progress, self._lib_text)

    # -- tab: behaviour ----------------------------------------------------------------------

    def _behaviour_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(self._cpu_preset_group())
        content = QWidget()
        outer.addWidget(content)
        outer.addStretch(1)
        form = self._form(content)
        self._row(
            form,
            "Creativity",
            self._decimal(("agents.chat.temperature",), 0.0, 2.0, 0.05),
            "Low = precise and repeatable, high = more varied wording. 0.6 suits chat.",
        )
        self._reply = self._spin(
            ("agents.chat.max_tokens", "agents.summarizer.max_tokens"),
            50,
            8000,
            step=50,
            suffix=" tokens",
            no_limit=True,
        )
        self._row(
            form,
            "Longest reply",
            self._reply,
            "A token is roughly three quarters of a word. Every token costs the same on a CPU.",
        )
        self._row(
            form,
            "",
            self._checkbox(
                ("agents.chat.think", "agents.executor.think", "agents.summarizer.think"),
                "Let the model think before answering",
            ),
            "Better on hard questions, noticeably slower. Only some models support it.",
        )
        self._row(
            form,
            "Steps per request",
            self._spin(("runtime.max_steps",), 1, 10),
            "How many rounds of tool use the assistant may take for one request.",
        )
        self._followups = self._choice(
            ("runtime.followups",),
            [
                ("auto", "Only when the request has several parts"),
                ("always", "Always let the model decide"),
                ("never", "Never (fastest)"),
            ],
            self._value("runtime.followups", "auto"),
        )
        self._row(form, "Follow-up steps", self._followups)
        self._fast_path = self._checkbox(
            ("runtime.fast_path",), "Skip the model for obvious, simple tools"
        )
        self._row(
            form,
            "",
            self._fast_path,
            "For things like “how much disk space is free?” the tool just runs.",
        )
        shown = int(self._value("runtime.direct_output_chars", 0)) > 0
        direct = self._direct = QCheckBox(
            "Show short results exactly as they are, without a summary"
        )
        direct.setChecked(shown)
        self._bind(
            ("runtime.direct_output_chars",),
            lambda: _DIRECT_OUTPUT_CHARS if direct.isChecked() else 0,
        )
        self._row(form, "", direct, "Fastest first answer for small, safe results.")
        self._row(
            form,
            "",
            self._checkbox(
                ("runtime.offer_original_output",),
                "Offer the original text after summarising pages and files",
            ),
        )
        return page

    def _cpu_preset_group(self) -> QGroupBox:
        group = QGroupBox("Quick preset")
        column = QVBoxLayout(group)
        intro = _label(
            "On a PC without a supported graphics card, speed comes from fewer, shorter model "
            "calls. This sets: small conversation memory (4096), replies up to 300 tokens, no "
            "extra follow-up steps, simple tools skip the model, short results shown as they "
            "are, and models stay loaded all day. Press Save afterwards to apply.",
            "help",
        )
        intro.setWordWrap(True)
        button = QPushButton("Fast on a CPU-only PC")
        button.setProperty("primary", True)
        button.clicked.connect(self._apply_cpu_preset)
        self._preset_note = _label("", "ok")
        column.addWidget(intro)
        column.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self._preset_note)
        return group

    def _apply_cpu_preset(self) -> None:
        """Fill in the controls (nothing is written until Save); the model choice is left alone."""
        self._ctx.setValue(4096)
        self._reply.setValue(300)
        self._followups.setCurrentIndex(self._followups.findData("never"))
        self._fast_path.setChecked(True)
        self._direct.setChecked(True)
        index = self._keep_alive.findData("24h")
        if index < 0:
            self._keep_alive.addItem("All day (24 hours)", "24h")
            index = self._keep_alive.findData("24h")
        self._keep_alive.setCurrentIndex(index)
        _say(self._preset_note, "Preset filled in. Press Save to apply.", "ok")

    # -- tab: safety -------------------------------------------------------------------------

    def _safety_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = _label(
            "Every tool has a risk level. Choose what happens before a tool of that kind runs.",
            "help",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        group = QGroupBox("Before running a tool that…")
        form = self._form(group)

        def mode_combo(level: str, allowed: list[str]) -> QComboBox:
            options = [
                (
                    m,
                    _APPROVAL_LABELS[m]
                    + (" (risky)" if level == "mutating" and m == "auto" else ""),
                )
                for m in allowed
            ]
            return self._choice(
                (f"safety.modes.{level}",), options, self._value(f"safety.modes.{level}")
            )

        self._mode_mutating = mode_combo("mutating", ["ask", "confirm", "auto"])
        self._mutating_before = self._mode_mutating.currentData()
        self._mode_mutating.currentIndexChanged.connect(self._warn_auto_mutating)
        self._row(
            form,
            "only reads information",
            mode_combo("read_only", ["auto", "ask", "confirm"]),
            "Examples: disk space, running processes, git status.",
        )
        self._row(
            form,
            "changes something",
            self._mode_mutating,
            "Examples: stopping a container, installing a package.",
        )
        self._row(
            form,
            "can destroy data",
            mode_combo("destructive", ["ask", "confirm"]),
            "Examples: deleting files, killing processes. It can never run automatically.",
        )
        layout.addWidget(group)
        layout.addWidget(
            self._checkbox(("safety.audit_log",), "Keep a log of every command the assistant runs")
        )
        note = _label("Fine-tune single tools on the Tools tab.", "help")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _warn_auto_mutating(self) -> None:
        if self._mode_mutating.currentData() != "auto":
            self._mutating_before = self._mode_mutating.currentData()
            return
        answer = QMessageBox.warning(
            self,
            "Run changes automatically?",
            "The assistant will change things on this PC without asking you first. "
            "Only do this if you trust the model and the tools. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._mode_mutating.setCurrentIndex(self._mode_mutating.findData(self._mutating_before))

    # -- tab: tools --------------------------------------------------------------------------

    def _tools_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self._tool_filter = QLineEdit()
        self._tool_filter.setPlaceholderText("Search tools…")
        self._tool_filter.textChanged.connect(self._filter_tools)
        self._tool_count = _label("", "help")
        top.addWidget(self._tool_filter, 1)
        top.addWidget(self._tool_count)
        layout.addLayout(top)

        report = load_packs(pack_roots(self._paths, self._settings))
        registry = ToolRegistry(report.tools.values(), current_platform())
        specs: dict[str, tuple[ToolSpec, str | None]] = {
            s.name: (s, None) for s in registry.available.values()
        }
        specs.update({n: (u.tool, u.reason) for n, u in registry.unavailable.items()})
        overrides = self._value("safety.tool_overrides", {})
        disabled = set(self._value("packs.disabled_tools", []))

        table = QTableWidget(len(specs), 5)
        table.setHorizontalHeaderLabels(["On", "Tool", "Risk", "What it does", "Before running"])
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setDefaultSectionSize(32)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self._tool_rows: dict[str, tuple[QTableWidgetItem, QComboBox | None, str | None]] = {}
        for row, (name, (spec, reason)) in enumerate(
            sorted(specs.items(), key=lambda i: (i[1][0].pack, i[0]))
        ):
            risk = spec.risk.value
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            on.setCheckState(Qt.CheckState.Unchecked if name in disabled else Qt.CheckState.Checked)
            title = QTableWidgetItem(name)
            title.setToolTip(spec.description)
            about = QTableWidgetItem(spec.description)
            about.setToolTip(spec.description)
            title.setData(Qt.ItemDataRole.UserRole, spec.pack)
            title.setToolTip(f"{spec.description}\n\nPack: {spec.pack}")
            risk_item = QTableWidgetItem(_RISK_TEXT[risk])
            risk_item.setForeground(QColor(_RISK_COLOR[risk]))
            table.setItem(row, 0, on)
            table.setItem(row, 1, title)
            table.setItem(row, 2, risk_item)
            table.setItem(row, 3, about)
            combo: QComboBox | None = None
            if reason is None:
                combo = QComboBox()
                combo.setStyleSheet("QComboBox { padding: 2px 8px; min-height: 16px; }")
                combo.addItem("Default", None)
                allowed = (
                    ["ask", "confirm", "deny"]
                    if risk == RiskLevel.DESTRUCTIVE.value
                    else ["auto", "ask", "confirm", "deny"]
                )
                for mode in allowed:
                    combo.addItem(_APPROVAL_LABELS[mode], mode)
                combo.setCurrentIndex(max(combo.findData(overrides.get(name)), 0))
                table.setCellWidget(row, 4, combo)
            else:
                for col in range(5):
                    item = table.item(row, col)
                    if item is not None:
                        item.setForeground(QColor("#5f688d"))
                        item.setToolTip(f"Not available on this PC: {reason}")
                on.setFlags(Qt.ItemFlag.NoItemFlags)
                na = QTableWidgetItem("not available here")
                na.setForeground(QColor("#5f688d"))
                table.setItem(row, 4, na)
            self._tool_rows[name] = (on, combo, reason)
        table.itemChanged.connect(lambda _i: self._update_tool_count())
        self._tool_table = table
        layout.addWidget(table, 1)
        hint = _label(
            "Untick a tool to hide it from the assistant. “Before running” overrides the Safety tab for that tool.",
            "help",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._update_tool_count()
        return page

    def _filter_tools(self, text: str) -> None:
        needle = text.strip().lower()
        table = self._tool_table
        for row in range(table.rowCount()):
            parts: list[str] = []
            for col in (1, 2, 3):
                item = table.item(row, col)
                if item is not None:
                    parts.append(item.text())
                    if col == 1:
                        parts.append(str(item.data(Qt.ItemDataRole.UserRole)))  # the pack name
            haystack = " ".join(parts).lower()
            table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _update_tool_count(self) -> None:
        usable = [r for r in self._tool_rows.values() if r[2] is None]
        enabled = sum(1 for on, _c, _r in usable if on.checkState() == Qt.CheckState.Checked)
        self._tool_count.setText(f"{enabled} of {len(usable)} tools on")

    # -- tab: memory -------------------------------------------------------------------------

    def _memory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = _label(
            "Things the assistant should always know, such as “my phone is 192.168.1.20”. "
            "These apply immediately.",
            "help",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._facts_table = QTableWidget(0, 2)
        self._facts_table.setHorizontalHeaderLabels(["Name", "Value"])
        self._facts_table.verticalHeader().hide()
        self._facts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._facts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._facts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._facts_table, 1)

        add = QHBoxLayout()
        self._fact_key = QLineEdit()
        self._fact_key.setPlaceholderText("Name (e.g. phone ip)")
        self._fact_value = QLineEdit()
        self._fact_value.setPlaceholderText("Value (e.g. 192.168.1.20:5555)")
        self._fact_value.returnPressed.connect(self._add_fact)
        button = QPushButton("Add")
        button.clicked.connect(self._add_fact)
        remove = QPushButton("Remove selected")
        remove.setProperty("danger", True)
        remove.clicked.connect(self._remove_fact)
        add.addWidget(self._fact_key, 1)
        add.addWidget(self._fact_value, 2)
        add.addWidget(button)
        layout.addLayout(add)
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignRight)
        self._fact_error = _label("", "bad")
        layout.addWidget(self._fact_error)
        self._reload_facts()
        return page

    def _reload_facts(self) -> None:
        facts = self._facts.all()
        self._facts_table.setRowCount(len(facts))
        for row, (key, value) in enumerate(facts.items()):
            self._facts_table.setItem(row, 0, QTableWidgetItem(key))
            self._facts_table.setItem(row, 1, QTableWidgetItem(value))

    def _add_fact(self) -> None:
        try:
            self._facts.remember(self._fact_key.text(), self._fact_value.text())
        except ValueError as exc:
            _say(self._fact_error, str(exc), "bad")
            return
        _say(self._fact_error, "", "help")
        self._fact_key.clear()
        self._fact_value.clear()
        self._reload_facts()

    def _remove_fact(self) -> None:
        for index in sorted({i.row() for i in self._facts_table.selectedIndexes()}, reverse=True):
            item = self._facts_table.item(index, 0)
            if item is not None:
                self._facts.forget(item.text())
        self._reload_facts()

    # -- tab: pet ------------------------------------------------------------------------------

    def _pet_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = _label(
            "Choose how the pet looks: one of the built-in characters, or your own artwork: "
            "one transparent image per expression in a folder (see the example).",
            "help",
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size"))
        self._size_combo = QComboBox()
        for label, pixels in PET_SIZES.items():
            self._size_combo.addItem(f"{label} ({pixels} px)", pixels)
        wanted_size = self._initial_size if self._initial_size else PET_SIZES[DEFAULT_SIZE]
        nearest = min(PET_SIZES.values(), key=lambda px: abs(px - wanted_size))
        self._size_combo.setCurrentIndex(max(self._size_combo.findData(nearest), 0))
        size_row.addWidget(self._size_combo, 1)
        layout.addLayout(size_row)

        row = QHBoxLayout()
        self._character_combo = QComboBox()
        self._character_combo.currentIndexChanged.connect(self._preview_character)
        row.addWidget(self._character_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._reload_characters)
        row.addWidget(refresh)
        layout.addLayout(row)

        self._character_preview = QLabel()
        self._character_preview.setFixedHeight(140)
        self._character_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._character_preview)
        self._character_info = _label("", "help")
        self._character_info.setWordWrap(True)
        layout.addWidget(self._character_info)

        buttons = QHBoxLayout()
        folder = QPushButton("Open characters folder")
        folder.clicked.connect(lambda: self._open_folder(self._paths.characters_dir))
        example = QPushButton("Create an example to edit")
        example.clicked.connect(self._create_example)
        buttons.addWidget(folder)
        buttons.addWidget(example)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        how = _label(
            "Files: neutral.png (required), then happy, love, surprised, sad, curious, dizzy, "
            "sleepy, sleeping, thinking, talking and blink. Any that are missing fall back to the "
            "closest one. PNG with a transparent background looks best, roughly 256 to 512 pixels.",
            "help",
        )
        how.setWordWrap(True)
        layout.addWidget(how)
        layout.addStretch(1)
        self._reload_characters()
        return page

    def _reload_characters(self) -> None:
        wanted = self._character_combo.currentData() if self._character_combo.count() else None
        wanted = self._initial_character if wanted is None else wanted
        combo = self._character_combo
        combo.blockSignals(True)
        combo.clear()
        for key, character in CHARACTERS.items():
            label = (
                character.name if key == "robot" else f"{character.name} \u00b7 {character.tagline}"
            )
            combo.addItem(label, "" if key == "robot" else f"builtin:{key}")
        for name in discover(self._paths.characters_dir):
            combo.addItem(f"{name} (your images)", name)
        combo.setCurrentIndex(max(combo.findData(wanted), 0))
        combo.blockSignals(False)
        self._preview_character()

    def _preview_character(self) -> None:
        name = self._character_combo.currentData() or ""
        sprites, vector = None, ROBOT
        if name.startswith("builtin:"):
            vector = CHARACTERS.get(name[len("builtin:") :], ROBOT)
        elif name:
            try:
                sprites = load_character(discover(self._paths.characters_dir)[name])
            except (KeyError, CharacterError) as exc:
                self._character_preview.clear()
                _say(self._character_info, f"Cannot use this character: {exc}", "bad")
                return
        self._character_preview.setPixmap(render_icon(size=128, sprites=sprites, vector=vector))
        if sprites is not None:
            have = ", ".join(sorted(sprites.images))
            _say(
                self._character_info,
                f"{sprites.name}: {len(sprites.images)} images ({have}).",
                "help",
            )
        else:
            _say(
                self._character_info,
                f"{vector.name}, {vector.tagline.lower()}. Follows your pointer and shows emotions.",
                "help",
            )

    def _create_example(self) -> None:
        folder = self._paths.characters_dir / "example-robot"
        write_example_character(folder)
        self._reload_characters()
        self._character_combo.setCurrentIndex(
            max(self._character_combo.findData("example-robot"), 0)
        )
        self._open_folder(folder)

    # -- tab: advanced -----------------------------------------------------------------------

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("Tool search")
        inner = self._form(group)
        self._row(
            inner,
            "Tools considered per request",
            self._spin(("retrieval.top_k",), 1, 30),
            "Fewer is faster and suits small models; more finds unusual tools.",
        )
        layout.addWidget(group)

        cpu = QGroupBox("Processor")
        cpu_form = self._form(cpu)
        self._row(
            cpu_form,
            "CPU threads",
            self._spin(
                ("models.main.num_thread", "models.router.num_thread"),
                1,
                256,
                no_limit=True,
                special="Automatic",
            ),
            "Leave on Automatic, or try your number of physical cores (not hyperthreads). "
            "Too many threads can slow answers down.",
        )
        layout.addWidget(cpu)

        server = QGroupBox(
            "Make Ollama itself faster (set as environment variables, then restart Ollama)"
        )
        tips = _label(
            "OLLAMA_FLASH_ATTENTION=1   uses less memory\n"
            "OLLAMA_KV_CACHE_TYPE=q8_0   shrinks the conversation cache when RAM is tight\n"
            "OLLAMA_NUM_PARALLEL=1   one request at a time, less memory reserved\n"
            "OLLAMA_KEEP_ALIVE=24h   keep models loaded (this app already sets its own)",
            "help",
        )
        tips.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        QVBoxLayout(server).addWidget(tips)
        layout.addWidget(server)

        files = QGroupBox("Files")
        column = QVBoxLayout(files)
        for text, path in (
            ("Settings file", self._store.path),
            ("Your own tool packs", self._paths.user_packs_dir),
            ("Data (sessions, memory, logs)", self._paths.data_dir),
        ):
            row = QHBoxLayout()
            name = QLabel(text)
            where = _label(str(path), "help")
            where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            open_ = QPushButton("Open folder")
            open_.clicked.connect(lambda _c=False, p=path: self._open_folder(p))
            row.addWidget(name)
            row.addWidget(where, 1)
            row.addWidget(open_)
            column.addLayout(row)
        layout.addWidget(files)

        env = sorted(k for k in os.environ if k.upper().startswith(SETTINGS_ENV_PREFIX))
        if env:
            warning = _label(
                "These environment variables override the file: " + ", ".join(env), "warn"
            )
            warning.setWordWrap(True)
            layout.addWidget(warning)

        actions = QHBoxLayout()
        fresh = QPushButton("Start a new conversation")
        fresh.clicked.connect(self._new_conversation)
        reset = QPushButton("Reset all settings…")
        reset.setProperty("danger", True)
        reset.clicked.connect(self._reset)
        actions.addWidget(fresh)
        actions.addStretch(1)
        actions.addWidget(reset)
        layout.addLayout(actions)
        layout.addStretch(1)
        return page

    def _open_folder(self, path: Any) -> None:
        folder = path if path.is_dir() else path.parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _new_conversation(self) -> None:
        self.new_conversation_requested.emit()
        self.accept()

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset settings?",
            "All your settings go back to the defaults. A backup of the file is kept next to it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if self._store.reset():
                self.saved.emit()
            self.accept()

    # -- saving ------------------------------------------------------------------------------

    def collect_changes(self) -> dict[str, Any]:
        """Dotted-path settings that differ from what was loaded."""
        changes: dict[str, Any] = {}
        for bind in self._binds:
            value = bind.read()
            if value != bind.initial:
                for path in bind.paths:
                    changes[path] = value
        mode = self._mode_mutating.currentData()
        allowed = bool(self._value("safety.allow_auto_mutating", False))
        if mode == "auto" and not allowed:
            changes["safety.allow_auto_mutating"] = True
        elif mode != "auto" and allowed:
            changes["safety.allow_auto_mutating"] = False
        changes.update(self._tool_changes())
        return changes

    def _tool_changes(self) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        known = set(self._tool_rows)
        before_off = list(self._value("packs.disabled_tools", []))
        off = {
            name
            for name, (on, _combo, reason) in self._tool_rows.items()
            if reason is None and on.checkState() == Qt.CheckState.Unchecked
        }
        # Keep what we cannot show: unknown names and tools unavailable on this PC.
        keep = {n for n in before_off if n not in known or self._tool_rows[n][2] is not None}
        disabled = sorted(off | keep)
        if disabled != sorted(before_off):
            changes["packs.disabled_tools"] = disabled

        before = dict(self._value("safety.tool_overrides", {}))
        overrides = {
            n: m for n, m in before.items() if n not in known or self._tool_rows[n][1] is None
        }
        for name, (_on, combo, _reason) in self._tool_rows.items():
            if combo is not None and combo.currentData() is not None:
                overrides[name] = combo.currentData()
        if overrides != before:
            changes["safety.tool_overrides"] = overrides
        return changes

    def _save(self) -> None:
        missing = self._missing()
        if missing:
            answer = QMessageBox.question(
                self,
                "Models not downloaded",
                "These models are not downloaded yet: " + ", ".join(missing) + ".\n"
                "The assistant will not work until they are. Save anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        size = int(self._size_combo.currentData())
        if size != self._initial_size:
            self.size_selected.emit(size)
        chosen = self._character_combo.currentData() or ""
        if chosen != self._initial_character:
            self.character_selected.emit(chosen)
        try:
            wrote = self._store.save(self.collect_changes())
        except ConfigError as exc:
            self._error.setText(str(exc))
            self._error.show()
            return
        if wrote:
            self.saved.emit()
        self.accept()

    def done(self, result: int) -> None:
        for job in list(self._jobs):
            job.cancelled = True
            job.wait(3000)
        self._facts.close()
        super().done(result)


def _title(entry: Any) -> str:
    return entry.label if entry.label == entry.tag else f"{entry.label}  ·  {entry.tag}"


def _label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label


def _say(label: QLabel, text: str, role: str) -> None:
    label.setText(text)
    label.setProperty("role", role)
    label.style().unpolish(label)
    label.style().polish(label)
