"""Right-side annotation form panel."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout,
    QSizePolicy, QFrame, QButtonGroup, QRadioButton,
)

from annotation_tool.data.project import ANOMALY_TYPES, AnnotationRecord


class AnnotationPanel(QWidget):
    """Form panel for entering/editing annotation properties.

    Signals:
        annotation_saved(AnnotationRecord)
        annotation_cleared(shp_index)
    """

    annotation_saved = pyqtSignal(object)   # AnnotationRecord
    annotation_cleared = pyqtSignal(int)    # shp_index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shp_index: int | None = None
        self._pixel_coords: list | None = None
        self._delta_t_auto: float | None = None
        self._setup_ui()

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.setInterval(500)
        self._confirm_timer.timeout.connect(self._auto_confirm)

        self._connect_field_signals()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_polygon(
        self,
        shp_index: int,
        pixel_coords: list,
        existing_rec: AnnotationRecord | None,
        auto_date: str = "",
        auto_time: str = "",
        auto_delta_t: float | None = None,
        auto_lon: float = 0.0,
        auto_lat: float = 0.0,
        auto_rack: str = "",
        auto_panel: str = "",
        auto_module: str = "",
        auto_row: str = "",
        auto_col: str = "",
    ):
        """Populate the panel for the given polygon."""
        self._confirm_timer.stop()
        self._shp_index = shp_index
        self._pixel_coords = pixel_coords
        self._auto_lon = auto_lon
        self._auto_lat = auto_lat
        self._delta_t_auto = auto_delta_t

        # Update auto-extracted section
        self._lbl_date.setText(auto_date or "—")
        self._lbl_time.setText(auto_time or "—")
        dt_text = f"{auto_delta_t:.2f} °C" if auto_delta_t is not None else "—"
        self._lbl_delta_t.setText(dt_text)
        self._lbl_panel_id.setText(f"#{shp_index}")

        _fields = [
            self._ed_rack, self._ed_panel, self._ed_module,
            self._ed_row, self._ed_col, self._ed_delta_t,
            self._ed_block, self._ed_panel_id_full,
        ]
        for w in _fields:
            w.blockSignals(True)
        self._anomaly_group.blockSignals(True)

        if existing_rec:
            self._ed_rack.setText(existing_rec.rack)
            self._ed_panel.setText(existing_rec.panel)
            self._ed_module.setText(existing_rec.module)
            self._ed_row.setText(existing_rec.row)
            self._ed_col.setText(existing_rec.col)
            idx = ANOMALY_TYPES.index(existing_rec.anomaly) if existing_rec.anomaly in ANOMALY_TYPES else 0
            self._radio_buttons[idx].setChecked(True)
            dt_val = str(existing_rec.delta_t) if existing_rec.delta_t else (str(auto_delta_t) if auto_delta_t is not None else "")
            self._ed_delta_t.setText(dt_val)
            self._ed_block.setText(existing_rec.block)
            self._ed_panel_id_full.setText(existing_rec.panel_id_full)
        else:
            self._ed_rack.setText(auto_rack)
            self._ed_panel.setText(auto_panel)
            self._ed_module.setText(auto_module)
            self._ed_row.setText(auto_row)
            self._ed_col.setText(auto_col)
            self._radio_buttons[0].setChecked(True)
            dt_default = f"{auto_delta_t:.2f}" if auto_delta_t is not None else ""
            self._ed_delta_t.setText(dt_default)
            self._ed_block.setText("")
            self._ed_panel_id_full.setText("")

        for w in _fields:
            w.blockSignals(False)
        self._anomaly_group.blockSignals(False)

        self._auto_date = auto_date
        self._auto_time = auto_time
        self._btn_clear.setEnabled(existing_rec is not None)
        _checked = self._anomaly_group.checkedButton()
        if _checked:
            _checked.setFocus()

    def set_anomaly_by_key(self, key: str) -> bool:
        """Set anomaly type by shortcut key and return True if valid."""
        from annotation_tool.data.project import KEY_TO_ANOMALY
        anomaly = KEY_TO_ANOMALY.get(key.lower())
        if anomaly and anomaly in ANOMALY_TYPES:
            self._radio_buttons[ANOMALY_TYPES.index(anomaly)].setChecked(True)
            return True
        return False

    @property
    def selected_shp_index(self) -> int | None:
        return self._shp_index

    def update_delta_t(self, val: float | None):
        """Update delta_t when projection result arrives late."""
        if val is not None and not self._ed_delta_t.text().strip():
            self._delta_t_auto = val
            self._ed_delta_t.blockSignals(True)
            self._ed_delta_t.setText(f"{val:.2f}")
            self._ed_delta_t.blockSignals(False)

    def trigger_save(self):
        """Programmatically trigger save (e.g. after key-press)."""
        if self._shp_index is not None:
            self._confirm_timer.stop()
            self._save()

    def clear_selection(self):
        """Reset panel to no-selection state."""
        self._confirm_timer.stop()
        self._shp_index = None
        self._lbl_panel_id.setText("—")
        self._lbl_date.setText("—")
        self._lbl_time.setText("—")
        self._lbl_delta_t.setText("—")
        self._btn_clear.setEnabled(False)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setFixedWidth(360)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        # Title
        title = QLabel("Annotation Panel")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px;")
        outer.addWidget(title)

        # Selected panel info
        info_box = QGroupBox("Selected Panel")
        info_layout = QFormLayout(info_box)
        info_layout.setSpacing(3)
        self._lbl_panel_id = QLabel("—")
        info_layout.addRow("Panel #:", self._lbl_panel_id)
        outer.addWidget(info_box)

        # Hidden labels kept for API compatibility (not shown)
        self._lbl_date = QLabel("—")
        self._lbl_time = QLabel("—")
        self._lbl_delta_t = QLabel("—")

        # Editable properties
        props_box = QGroupBox("Properties")
        props_layout = QFormLayout(props_box)
        props_layout.setSpacing(5)

        self._ed_rack = QLineEdit()
        self._ed_rack.setPlaceholderText("e.g. R1")
        props_layout.addRow("Rack:", self._ed_rack)

        self._ed_panel = QLineEdit()
        self._ed_panel.setPlaceholderText("e.g. P3")
        props_layout.addRow("Panel:", self._ed_panel)

        self._ed_module = QLineEdit()
        self._ed_module.setPlaceholderText("e.g. M1")
        props_layout.addRow("Module:", self._ed_module)

        self._ed_row = QLineEdit()
        self._ed_row.setPlaceholderText("e.g. 1")

        self._ed_col = QLineEdit()
        self._ed_col.setPlaceholderText("e.g. 1")

        self._anomaly_group = QButtonGroup(self)
        self._anomaly_group.setExclusive(True)
        self._radio_buttons: list[QRadioButton] = []

        defect_container = QWidget()
        defect_grid = QGridLayout(defect_container)
        defect_grid.setContentsMargins(0, 0, 0, 0)
        defect_grid.setHorizontalSpacing(6)
        defect_grid.setVerticalSpacing(2)
        _COLS = 2
        for i, anomaly in enumerate(ANOMALY_TYPES):
            btn = QRadioButton(anomaly)
            self._anomaly_group.addButton(btn, i)
            defect_grid.addWidget(btn, i // _COLS, i % _COLS)
            self._radio_buttons.append(btn)
        self._radio_buttons[0].setChecked(True)
        props_layout.addRow("Defect:", defect_container)

        self._ed_delta_t = QLineEdit()
        self._ed_delta_t.setPlaceholderText("ΔT in °C")
        props_layout.addRow("ΔT override:", self._ed_delta_t)

        self._ed_block = QLineEdit()
        self._ed_block.setPlaceholderText("Block number")
        props_layout.addRow("Block:", self._ed_block)

        self._ed_panel_id_full = QLineEdit()
        self._ed_panel_id_full.setPlaceholderText("Full panel ID")
        props_layout.addRow("Full ID:", self._ed_panel_id_full)

        outer.addWidget(props_box)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._btn_clear = QPushButton("Clear [Del]")
        self._btn_clear.setEnabled(False)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_clear.setStyleSheet("background-color: #7a2a2a; color: white; padding: 6px;")
        btn_layout.addWidget(self._btn_clear)
        outer.addLayout(btn_layout)

        # Keyboard hint
        hint_lines = [
            "Shortcuts:",
            "1=Cell          2=Multi Cell",
            "3=Bypass Diode  4=Mod.Offline",
            "5=Mod.Missing   6=Part.String",
            "7=Phys.Damage   8=Shading",
            "9=Short Circuit 0=Str.Offline",
            "S=Short Circuit V=Vegetation",
            "D=Dust",
            "←/→/A/D/N/M prev/next image",
            "Ctrl+Z undo  Ctrl+Y redo",
            "F = fit to window",
            "Scroll = zoom  Alt+drag = pan",
        ]
        hint = QLabel("\n".join(hint_lines))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaaaaa; font-size: 10px; padding: 4px;")
        outer.addWidget(hint)

        outer.addStretch()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect_field_signals(self):
        for ed in (self._ed_rack, self._ed_panel, self._ed_module,
                   self._ed_row, self._ed_col, self._ed_delta_t,
                   self._ed_block, self._ed_panel_id_full):
            ed.textChanged.connect(self._on_field_changed)
        self._anomaly_group.buttonToggled.connect(
            lambda btn, checked: self._on_field_changed()
        )

    def _on_field_changed(self, *args):
        if self._shp_index is not None:
            self._confirm_timer.start()

    def _auto_confirm(self):
        if self._shp_index is not None:
            self._save()

    def _save(self):
        if self._shp_index is None:
            return
        try:
            delta_t_text = self._ed_delta_t.text().strip()
            delta_t = float(delta_t_text) if delta_t_text else (self._delta_t_auto or 0.0)
        except ValueError:
            delta_t = self._delta_t_auto or 0.0

        _checked = self._anomaly_group.checkedButton()
        rec = AnnotationRecord(
            shp_index=self._shp_index,
            anomaly=_checked.text() if _checked else ANOMALY_TYPES[0],
            rack=self._ed_rack.text().strip(),
            panel=self._ed_panel.text().strip(),
            module=self._ed_module.text().strip(),
            row=self._ed_row.text().strip(),
            col=self._ed_col.text().strip(),
            image_name="",   # filled in by AnnotationScreen
            date=self._auto_date,
            time=self._auto_time,
            delta_t=round(delta_t, 2),
            longitude=getattr(self, "_auto_lon", 0.0),
            latitude=getattr(self, "_auto_lat", 0.0),
            block=self._ed_block.text().strip(),
            panel_id_full=self._ed_panel_id_full.text().strip(),
            pixel_coords=self._pixel_coords,
        )
        self._btn_clear.setEnabled(True)
        self.annotation_saved.emit(rec)

    def _clear(self):
        if self._shp_index is not None:
            idx = self._shp_index
            self._btn_clear.setEnabled(False)
            self.annotation_cleared.emit(idx)
