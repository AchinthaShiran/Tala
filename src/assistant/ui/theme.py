"""Shared dark theme for the settings window (the chat window carries its own copy of the basics)."""

from __future__ import annotations

STYLE = """
QDialog, QWidget#root { background: #1b2033; color: #e8ebf7; font-size: 13px; }
QLabel { color: #e8ebf7; }
QLabel[role="help"] { color: #8d97bd; font-size: 11px; }
QLabel[role="title"] { font-size: 18px; font-weight: 600; color: #f2f4ff; }
QLabel[role="ok"] { color: #5be37d; }
QLabel[role="warn"] { color: #ffc247; }
QLabel[role="bad"] { color: #ff7b7b; }
QTabWidget::pane { border: 1px solid #323a58; border-radius: 10px; top: -1px; background: #1e2439; }
QTabBar::tab { background: transparent; color: #98a2c8; padding: 8px 14px; margin-right: 2px;
               border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #1e2439; color: #f2f4ff; border: 1px solid #323a58;
                        border-bottom-color: #1e2439; }
QTabBar::tab:hover:!selected { color: #f2f4ff; }
QGroupBox { border: 1px solid #323a58; border-radius: 10px; margin-top: 14px; padding: 14px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #98a2c8; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #11162a; color: #f2f4ff; border: 1px solid #323a58; border-radius: 8px;
    padding: 6px 8px; min-height: 18px; selection-background-color: #4a69d8; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #4a69d8; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #11162a; color: #f2f4ff; border: 1px solid #323a58;
                              selection-background-color: #4a69d8; outline: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #4a5483;
                       background: #11162a; }
QCheckBox::indicator:checked { background: #4a69d8; border-color: #4a69d8; }
QTableWidget, QListWidget { background: #11162a; border: 1px solid #323a58; border-radius: 8px;
                            gridline-color: #232a45; outline: none; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected, QListWidget::item:selected { background: #2f3a63; color: white; }
QHeaderView::section { background: #232a45; color: #98a2c8; border: none; padding: 6px; }
QPushButton { background: #2f3a63; color: #f2f4ff; border: none; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: #3b4880; }
QPushButton:disabled { background: #232a45; color: #5f688d; }
QPushButton[primary="true"] { background: #4a69d8; }
QPushButton[primary="true"]:hover { background: #5a78e6; }
QPushButton[primary="true"]:disabled { background: #232a45; color: #5f688d; }
QPushButton[danger="true"] { background: #7a2e3b; }
QPushButton[danger="true"]:hover { background: #94384a; }
QProgressBar { background: #11162a; border: 1px solid #323a58; border-radius: 6px; height: 10px;
               text-align: center; color: transparent; }
QProgressBar::chunk { background: #4a69d8; border-radius: 5px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a4366; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #11162a; color: #f2f4ff; border: 1px solid #323a58; padding: 4px; }
"""
