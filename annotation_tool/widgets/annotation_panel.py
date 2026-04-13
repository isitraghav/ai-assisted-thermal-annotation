"""Right-side annotation form panel."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QGroupBox, QFormLayout,
    QSizePolicy, QFrame, QScrollArea,
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

        if existing_rec:
            self._ed_rack.setText(existing_rec.rack)
            self._ed_panel.setText(existing_rec.panel)
            self._ed_module.setText(existing_rec.module)
            self._ed_row.setText(existing_rec.row)
            self._ed_col.setText(existing_rec.col)
            idx = ANOMALY_TYPES.index(existing_rec.anomaly) if existing_rec.anomaly in ANOMALY_TYPES else 0
            self._cb_anomaly.setCurrentIndex(idx)
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
            self._cb_anomaly.setCurrentIndex(0)
            dt_default = f"{auto_delta_t:.2f}" if auto_delta_t is not None else ""
            self._ed_delta_t.setText(dt_default)
            self._ed_block.setText("")
            self._ed_panel_id_full.setText("")

        self._auto_date = auto_date
        self._auto_time = auto_time
        self._btn_save.setEnabled(True)
        self._btn_clear.setEnabled(existing_rec is not None)
        self._cb_anomaly.setFocus()

    def set_anomaly_by_key(self, key: str) -> bool:
        """Set anomaly type by shortcut key and return True if valid."""
        from annotation_tool.data.project import KEY_TO_ANOMALY
        anomaly = KEY_TO_ANOMALY.get(key.lower())
        if anomaly and anomaly in ANOMALY_TYPES:
            self._cb_anomaly.setCurrentIndex(ANOMALY_TYPES.index(anomaly))
            return True
        return False

    def trigger_save(self):
        """Programmatically trigger save (e.g. after key-press)."""
        if self._shp_index is not None:
            self._save()

    def clear_selection(self):
        """Reset panel to no-selection state."""
        self._shp_index = None
        self._lbl_panel_id.setText("—")
        self._lbl_date.setText("—")
        self._lbl_time.setText("—")
        self._lbl_delta_t.setText("—")
        self._btn_save.setEnabled(False)
        self._btn_clear.setEnabled(False)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setFixedWidth(300)
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

        # Auto-extracted info
        auto_box = QGroupBox("Auto-extracted")
        auto_layout = QFormLayout(auto_box)
        auto_layout.setSpacing(3)
        self._lbl_date = QLabel("—")
        self._lbl_time = QLabel("—")
        self._lbl_delta_t = QLabel("—")
        auto_layout.addRow("Date:", self._lbl_date)
        auto_layout.addRow("Time:", self._lbl_time)
        auto_layout.addRow("ΔT:", self._lbl_delta_t)
        outer.addWidget(auto_box)

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
        props_layout.addRow("row:", self._ed_row)

        self._ed_col = QLineEdit()
        self._ed_col.setPlaceholderText("e.g. 1")
        props_layout.addRow("col:", self._ed_col)

        self._cb_anomaly = QComboBox()
        self._cb_anomaly.addItems(ANOMALY_TYPES)
        props_layout.addRow("Defect:", self._cb_anomaly)

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
        self._btn_save = QPushButton("Save [Enter]")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save)
        self._btn_save.setStyleSheet("background-color: #2a7a2a; color: white; font-weight: bold; padding: 6px;")
        btn_layout.addWidget(self._btn_save)

        self._btn_clear = QPushButton("Clear [Del]")
        self._btn_clear.setEnabled(False)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_clear.setStyleSheet("background-color: #7a2a2a; color: white; padding: 6px;")
        btn_layout.addWidget(self._btn_clear)
        outer.addLayout(btn_layout)

        # Keyboard hint
        hint_lines = [
            "Shortcuts:",
            "1=Bypass Diode  2=Cell",
            "3=Dust          4=Mod.Missing",
            "5=Mod.Offline   6=Multi Cell",
            "7=Part.String   8=Phys.Damage",
            "9=Shading       0=Str.Offline",
            "S=Short Circuit V=Vegetation",
            "←/→ prev/next image",
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

    def _save(self):
        if self._shp_index is None:
            return
        try:
            delta_t_text = self._ed_delta_t.text().strip()
            delta_t = float(delta_t_text) if delta_t_text else (self._delta_t_auto or 0.0)
        except ValueError:
            delta_t = self._delta_t_auto or 0.0

        rec = AnnotationRecord(
            shp_index=self._shp_index,
            anomaly=self._cb_anomaly.currentText(),
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
        )
        self._btn_clear.setEnabled(True)
        self.annotation_saved.emit(rec)

    def _clear(self):
        if self._shp_index is not None:
            idx = self._shp_index
            self._btn_clear.setEnabled(False)
            self.annotation_cleared.emit(idx)
