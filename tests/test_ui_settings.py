"""Settings page: the config writer (no Qt) and the dialog's change detection (offscreen)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from assistant.config import AppPaths
from assistant.domain import ConfigError
from assistant.ui.config_store import ConfigStore, dig


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    return ConfigStore(tmp_path / "config" / "config.yaml")


def read(store: ConfigStore) -> dict:
    return yaml.safe_load(store.path.read_text(encoding="utf-8"))


def test_save_writes_only_the_changed_values(store):
    assert store.save({"runtime.max_steps": 5, "agents.chat.temperature": 0.4}) is True
    assert read(store) == {"runtime": {"max_steps": 5}, "agents": {"chat": {"temperature": 0.4}}}
    settings = store.load()
    assert settings.runtime.max_steps == 5 and settings.agents["chat"].temperature == 0.4
    assert settings.agents["chat"].model == "main"  # untouched keys keep their defaults


def test_second_save_merges_and_keeps_a_backup(store):
    store.save({"runtime.max_steps": 5})
    store.save({"runtime.fast_path": False})
    assert read(store)["runtime"] == {"max_steps": 5, "fast_path": False}
    assert yaml.safe_load(store.backup_path.read_text(encoding="utf-8"))["runtime"] == {
        "max_steps": 5
    }


def test_invalid_change_is_rejected_and_the_file_is_untouched(store):
    store.save({"runtime.max_steps": 5})
    before = store.path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        store.save({"safety.modes.destructive": "auto"})
    with pytest.raises(ConfigError):
        store.save({"runtime.max_steps": 99})
    assert store.path.read_text(encoding="utf-8") == before


def test_dict_values_replace_so_entries_can_be_removed(store):
    store.save({"safety.tool_overrides": {"git_status": "auto", "docker_ps": "ask"}})
    store.save({"safety.tool_overrides": {"docker_ps": "ask"}})
    assert read(store)["safety"]["tool_overrides"] == {"docker_ps": "ask"}


def test_no_changes_does_not_create_a_file(store):
    assert store.save({}) is False
    assert not store.path.exists()


def test_reset_keeps_a_backup_and_returns_to_defaults(store):
    store.save({"runtime.max_steps": 7})
    assert store.reset() is True
    assert not store.path.exists() and store.backup_path.exists()
    assert store.load().runtime.max_steps == 3


def test_dig_reads_nested_values_with_default():
    assert dig({"a": {"b": 1}}, "a.b") == 1
    assert dig({"a": {"b": 1}}, "a.c", "x") == "x"
    assert dig({"a": None}, "a", 5) == 5


# -- dialog (skipped when PySide6 is not installed) ----------------------------------------------

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from assistant.ui.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp, tmp_path):
    paths = AppPaths(tmp_path / "config", tmp_path / "data")
    paths.ensure()
    store = ConfigStore(paths.config_file)
    dlg = SettingsDialog(store, paths, auto_check=False)
    yield dlg
    dlg.close()


def test_untouched_dialog_reports_no_changes(dialog):
    assert dialog.collect_changes() == {}


def test_changed_controls_become_dotted_settings(dialog):
    dialog._main.setCurrentText("qwen3:8b")
    changes = dialog.collect_changes()
    assert changes == {"models.main.name": "qwen3:8b"}


def test_url_applies_to_every_model_and_embeddings(dialog):
    dialog._url.setText("http://box:11434")
    assert dialog.collect_changes() == {
        "models.main.base_url": "http://box:11434",
        "models.router.base_url": "http://box:11434",
        "embeddings.base_url": "http://box:11434",
    }


def test_choosing_auto_for_changes_also_sets_the_required_flag(dialog, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._mode_mutating.setCurrentIndex(dialog._mode_mutating.findData("auto"))
    changes = dialog.collect_changes()
    assert changes["safety.modes.mutating"] == "auto"
    assert changes["safety.allow_auto_mutating"] is True


def test_declining_the_auto_warning_reverts_the_choice(dialog, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog._mode_mutating.setCurrentIndex(dialog._mode_mutating.findData("auto"))
    assert dialog.collect_changes() == {}


def test_destructive_tools_cannot_be_set_to_auto(dialog):
    for _name, (_on, combo, _reason) in dialog._tool_rows.items():
        if combo is not None and combo.findData("auto") < 0:
            return
    pytest.fail("expected at least one destructive tool without an 'auto' choice")


def test_unticking_a_tool_disables_it_and_override_is_saved(dialog):
    name = next(n for n, (_o, c, _r) in dialog._tool_rows.items() if c is not None)
    other = next(n for n, (_o, c, _r) in dialog._tool_rows.items() if c is not None and n != name)
    dialog._tool_rows[name][0].setCheckState(Qt.CheckState.Unchecked)
    combo = dialog._tool_rows[other][1]
    combo.setCurrentIndex(combo.findData("deny"))
    changes = dialog.collect_changes()
    assert changes["packs.disabled_tools"] == [name]
    assert changes["safety.tool_overrides"] == {other: "deny"}


def test_save_writes_the_file_and_signals(dialog):
    seen = []
    dialog.saved.connect(lambda: seen.append(True))
    dialog._main.setCurrentText("qwen3:8b")
    dialog._save()
    assert seen == [True]
    assert dialog._store.load().models["main"].name == "qwen3:8b"


def test_invalid_value_shows_an_error_and_keeps_the_dialog_open(dialog, monkeypatch):
    monkeypatch.setattr(
        dialog._store, "save", lambda _c: (_ for _ in ()).throw(ConfigError("nope"))
    )
    dialog._main.setCurrentText("x")
    dialog._save()
    assert dialog._error.text() == "nope" and not dialog._error.isHidden()


def test_facts_are_added_and_removed_immediately(dialog):
    dialog._fact_key.setText("Phone IP")
    dialog._fact_value.setText("192.168.1.20")
    dialog._add_fact()
    assert dialog._facts.all() == {"phone ip": "192.168.1.20"}
    dialog._facts_table.selectRow(0)
    dialog._remove_fact()
    assert dialog._facts.all() == {}


def test_library_lists_catalog_models_with_install_state(dialog):
    from assistant.setup import Hardware

    dialog._installed = {"gemma4:e2b"}
    dialog._on_hardware(Hardware(system="Windows", ram_gb=8.0))  # small PC: nothing too heavy
    rows = {e.tag: dialog._library.item(i, 5).text() for i, e in enumerate(dialog._library_entries)}
    assert rows["gemma4:e2b"].startswith("Installed")
    assert rows["gemma4:e4b"].startswith("Not installed")
    assert "too big" in rows["gpt-oss:20b"]
    assert (
        "★"
        in dialog._library.item(
            [e.tag for e in dialog._library_entries].index(dialog._recommended_tag), 0
        ).text()
    )


def test_library_buttons_pick_models_without_saving(dialog):
    tags = [e.tag for e in dialog._library_entries]
    dialog._installed = set()
    dialog._library.selectRow(tags.index("gemma4:e4b"))
    assert dialog._lib_main.isEnabled() and dialog._lib_install.isEnabled()
    assert not dialog._lib_router.isEnabled()  # not a router-sized model
    dialog._lib_main.click()
    assert dialog.collect_changes() == {"models.main.name": "gemma4:e4b"}
    dialog._library.selectRow(tags.index("granite4.1:3b"))
    assert dialog._lib_router.isEnabled()
