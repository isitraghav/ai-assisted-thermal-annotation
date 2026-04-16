"""Image navigation widget: prev/next buttons + counter."""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy,
)


class ImageNavigator(QWidget):
    """Prev / Next buttons with image counter and filename label."""

    navigate = pyqtSignal(int)         # emits absolute image index
    toggle_markings = pyqtSignal()     # emits when polygon visibility toggled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = 0
        self._current = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self._btn_prev = QPushButton("← Prev")
        self._btn_prev.setFixedWidth(80)
        self._btn_prev.clicked.connect(self._go_prev)
        layout.addWidget(self._btn_prev)

        self._counter_label = QLabel("0 / 0")
        self._counter_label.setAlignment(Qt.AlignCenter)
        self._counter_label.setMinimumWidth(90)
        layout.addWidget(self._counter_label)

        self._btn_next = QPushButton("Next →")
        self._btn_next.setFixedWidth(80)
        self._btn_next.clicked.connect(self._go_next)
        layout.addWidget(self._btn_next)

        self._filename_label = QLabel("")
        self._filename_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._filename_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self._filename_label)

        self._annotated_label = QLabel("")
        self._annotated_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._annotated_label.setMinimumWidth(120)
        layout.addWidget(self._annotated_label)

        self._btn_toggle = QPushButton("Hide Polygons")
        self._btn_toggle.setFixedWidth(110)
        self._btn_toggle.setCheckable(True)
        self._btn_toggle.setChecked(True)
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self._btn_toggle)

    def _on_toggle_clicked(self, checked: bool):
        self._btn_toggle.setText("Hide Polygons" if checked else "Show Polygons")
        self.toggle_markings.emit()

    def set_toggle_state(self, visible: bool):
        """Sync button state without emitting signal (e.g. when Q key used)."""
        self._btn_toggle.blockSignals(True)
        self._btn_toggle.setChecked(visible)
        self._btn_toggle.setText("Hide Polygons" if visible else "Show Polygons")
        self._btn_toggle.blockSignals(False)

    def set_state(self, current: int, total: int, filename: str = "", annotated: int = 0):
        self._current = current
        self._total = total
        self._counter_label.setText(f"{current + 1} / {total}")
        self._filename_label.setText(filename)
        self._annotated_label.setText(f"{annotated} annotated")
        self._btn_prev.setEnabled(current > 0)
        self._btn_next.setEnabled(current < total - 1)

    def _go_prev(self):
        if self._current > 0:
            self.navigate.emit(self._current - 1)

    def _go_next(self):
        if self._current < self._total - 1:
            self.navigate.emit(self._current + 1)
