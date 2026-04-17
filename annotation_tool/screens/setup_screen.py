"""Setup screen: file/folder selection before starting annotation."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QFileDialog,
    QMessageBox, QFrame, QRadioButton, QButtonGroup, QComboBox,
)

import shutil
import tempfile

from annotation_tool.data.project import load_project, ProjectState
from annotation_tool.data.recent_sessions import load_recent, save_recent


class SetupScreen(QWidget):
    """File-picker screen.

    Emits setup_complete(ProjectState) when the user clicks Start.
    Emits resume_session(ProjectState, session_path) when resuming.
    """

    setup_complete = pyqtSignal(object, object)   # project, session_path (may be None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(16)

        title = QLabel("Thermal Annotation Tool")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 10px;")
        outer.addWidget(title)

        subtitle = QLabel("Select project files to begin annotation")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; font-size: 13px;")
        outer.addWidget(subtitle)

        # ---- Recent sessions ----
        recent_box = QGroupBox("Recent Sessions")
        recent_layout = QHBoxLayout(recent_box)
        recent_layout.setSpacing(8)
        self._recent_combo = QComboBox()
        self._recent_combo.addItem("— select a recent session —", None)
        for entry in load_recent():
            self._recent_combo.addItem(entry.get("label", "?"), entry)
        btn_load_recent = QPushButton("Load")
        btn_load_recent.setFixedWidth(70)
        btn_load_recent.clicked.connect(self._load_recent)
        recent_layout.addWidget(self._recent_combo, stretch=1)
        recent_layout.addWidget(btn_load_recent)
        outer.addWidget(recent_box)

        # ---- Drone model ----
        drone_box = QGroupBox("Drone Model")
        drone_layout = QHBoxLayout(drone_box)
        drone_layout.setSpacing(20)

        self._drone_group = QButtonGroup(self)
        self._rb_m3t = QRadioButton("DJI M3T  (640 × 512)")
        self._rb_m4t = QRadioButton("DJI M4T  (1280 × 1024)")
        self._rb_m3t.setChecked(True)
        self._drone_group.addButton(self._rb_m3t)
        self._drone_group.addButton(self._rb_m4t)
        drone_layout.addStretch()
        drone_layout.addWidget(self._rb_m3t)
        drone_layout.addWidget(self._rb_m4t)
        drone_layout.addStretch()
        outer.addWidget(drone_box)

        # ---- Project files ----
        files_box = QGroupBox("Project Files")
        files_layout = QFormLayout(files_box)
        files_layout.setSpacing(10)

        self._ed_image_dir = QLineEdit()
        self._ed_image_dir.setPlaceholderText("Folder containing thermal JPG images")
        files_layout.addRow("Image folder:", self._make_browse_row(
            self._ed_image_dir, self._browse_image_dir
        ))

        self._ed_shapefile = QLineEdit()
        self._ed_shapefile.setPlaceholderText("Panel polygon shapefile (.shp)")
        files_layout.addRow("Shapefile (.shp):", self._make_browse_row(
            self._ed_shapefile, self._browse_shapefile
        ))

        self._ed_shx = QLineEdit()
        self._ed_shx.setPlaceholderText("Shapefile index (.shx) — leave blank if same folder as .shp")
        files_layout.addRow("Shapefile (.shx):", self._make_browse_row(
            self._ed_shx, self._browse_shx
        ))

        self._ed_dbf = QLineEdit()
        self._ed_dbf.setPlaceholderText("Shapefile attributes (.dbf) — leave blank if same folder as .shp")
        files_layout.addRow("Shapefile (.dbf):", self._make_browse_row(
            self._ed_dbf, self._browse_dbf
        ))

        self._ed_dem = QLineEdit()
        self._ed_dem.setPlaceholderText("Digital elevation model (.tif)")
        files_layout.addRow("DEM file:", self._make_browse_row(
            self._ed_dem, self._browse_dem
        ))

        self._ed_cameras = QLineEdit()
        self._ed_cameras.setPlaceholderText("Agisoft Metashape cameras.xml")
        files_layout.addRow("cameras.xml:", self._make_browse_row(
            self._ed_cameras, self._browse_cameras
        ))

        self._ed_output = QLineEdit()
        self._ed_output.setPlaceholderText("Output GeoJSON path (created automatically)")
        files_layout.addRow("Output GeoJSON:", self._make_browse_row(
            self._ed_output, self._browse_output, save=True
        ))

        outer.addWidget(files_box)

        # ---- Import ----
        resume_box = QGroupBox("Import Existing Annotations (optional)")
        resume_layout = QFormLayout(resume_box)
        resume_layout.setSpacing(8)

        self._ed_import_geojson = QLineEdit()
        self._ed_import_geojson.setPlaceholderText("Existing GeoJSON report to import")
        resume_layout.addRow("Import GeoJSON:", self._make_browse_row(
            self._ed_import_geojson, self._browse_import_geojson
        ))

        self._ed_session = QLineEdit()
        self._ed_session.setPlaceholderText("Existing session file to resume (.session.json)")
        resume_layout.addRow("Resume session:", self._make_browse_row(
            self._ed_session, self._browse_session
        ))

        outer.addWidget(resume_box)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_autodetect = QPushButton("Auto-detect from folder")
        self._btn_autodetect.clicked.connect(self._autodetect)
        btn_row.addWidget(self._btn_autodetect)

        self._btn_start = QPushButton("Start Annotation →")
        self._btn_start.setStyleSheet(
            "background-color: #2a7a2a; color: white; font-weight: bold; "
            "padding: 10px 20px; font-size: 14px;"
        )
        self._btn_start.clicked.connect(self._start)
        btn_row.addWidget(self._btn_start)
        outer.addLayout(btn_row)

        outer.addStretch()

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: #cc4444;")
        outer.addWidget(self._status)

    def _make_browse_row(self, lineedit: QLineEdit, callback, save: bool = False) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(lineedit)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        btn.clicked.connect(callback)
        h.addWidget(btn)
        return w

    # ------------------------------------------------------------------
    # Browse callbacks
    # ------------------------------------------------------------------

    def _load_recent(self):
        entry = self._recent_combo.currentData()
        if not entry:
            return
        self._ed_image_dir.setText(entry.get("image_dir", ""))
        self._ed_shapefile.setText(entry.get("shapefile", ""))
        self._ed_shx.setText(entry.get("shx", ""))
        self._ed_dbf.setText(entry.get("dbf", ""))
        self._ed_dem.setText(entry.get("dem", ""))
        self._ed_cameras.setText(entry.get("cameras_xml", ""))
        self._ed_output.setText(entry.get("output_geojson", ""))
        self._ed_session.setText(entry.get("session_file", ""))
        self._ed_import_geojson.setText("")
        if entry.get("drone_model") == "M4T":
            self._rb_m4t.setChecked(True)
        else:
            self._rb_m3t.setChecked(True)

    def _browse_image_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select image folder")
        if d:
            self._ed_image_dir.setText(d)

    def _browse_shapefile(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select shapefile", filter="Shapefiles (*.shp)")
        if f:
            self._ed_shapefile.setText(f)

    def _browse_shx(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select .shx file", filter="Shapefile index (*.shx)")
        if f:
            self._ed_shx.setText(f)

    def _browse_dbf(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select .dbf file", filter="Shapefile attributes (*.dbf)")
        if f:
            self._ed_dbf.setText(f)

    def _browse_dem(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select DEM", filter="GeoTIFF (*.tif *.tiff)")
        if f:
            self._ed_dem.setText(f)

    def _browse_cameras(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select cameras.xml", filter="XML (*.xml)")
        if f:
            self._ed_cameras.setText(f)

    def _browse_output(self):
        f, _ = QFileDialog.getSaveFileName(
            self, "Output GeoJSON path", filter="GeoJSON (*.geojson)"
        )
        if f:
            if not f.endswith(".geojson"):
                f += ".geojson"
            self._ed_output.setText(f)

    def _browse_import_geojson(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select GeoJSON report", filter="GeoJSON (*.geojson *.json)")
        if f:
            self._ed_import_geojson.setText(f)

    def _browse_session(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select session file", filter="Session (*.session.json *.json)")
        if f:
            self._ed_session.setText(f)

    # ------------------------------------------------------------------
    # Auto-detect
    # ------------------------------------------------------------------

    def _autodetect(self):
        d = self._ed_image_dir.text().strip()
        if not d:
            QMessageBox.warning(self, "Auto-detect", "Please select an image folder first.")
            return
        self._autodetect_from_dir(Path(d))

    def _autodetect_from_dir(self, folder: Path):
        search_dirs = [folder, folder.parent]
        for sd in search_dirs:
            # Shapefile + sidecars
            shps = list(sd.glob("*.shp"))
            if shps and not self._ed_shapefile.text():
                shp = shps[0]
                self._ed_shapefile.setText(str(shp))
                # Auto-fill .shx and .dbf if found (may be same or different dir)
                for ext, ed in ((".shx", self._ed_shx), (".dbf", self._ed_dbf)):
                    if not ed.text():
                        sidecar = shp.with_suffix(ext)
                        if sidecar.exists():
                            ed.setText(str(sidecar))
                        else:
                            # Search both dirs for matching stem
                            for ssd in search_dirs:
                                candidates = list(ssd.glob(f"*{ext}"))
                                if candidates:
                                    ed.setText(str(candidates[0]))
                                    break

            # Fill .shx / .dbf independently if shp was already set
            if self._ed_shapefile.text():
                shp = Path(self._ed_shapefile.text())
                for ext, ed in ((".shx", self._ed_shx), (".dbf", self._ed_dbf)):
                    if not ed.text():
                        sidecar = shp.with_suffix(ext)
                        if sidecar.exists():
                            ed.setText(str(sidecar))
                        else:
                            for ssd in search_dirs:
                                candidates = list(ssd.glob(f"*{ext}"))
                                if candidates:
                                    ed.setText(str(candidates[0]))
                                    break

            tifs = list(sd.glob("*.tif")) + list(sd.glob("*.tiff"))
            tifs = [t for t in tifs if "dem" in t.name.lower() or "DEM" in t.name]
            if not tifs:
                tifs = list(sd.glob("DEM.tif")) + list(sd.glob("DEM.tiff"))
            if tifs and not self._ed_dem.text():
                self._ed_dem.setText(str(tifs[0]))

            xmls = list(sd.glob("cameras.xml"))
            if xmls and not self._ed_cameras.text():
                self._ed_cameras.setText(str(xmls[0]))

            # Session file
            sessions = list(sd.glob("*.session.json"))
            if sessions and not self._ed_session.text():
                self._ed_session.setText(str(sessions[0]))

            # GeoJSON output / import
            geojsons = list(sd.glob("*.geojson"))
            if geojsons:
                # Prefer one that looks like output (not a source shapefile export)
                for gj in geojsons:
                    if not self._ed_output.text():
                        self._ed_output.setText(str(gj))
                    elif not self._ed_import_geojson.text() and str(gj) != self._ed_output.text():
                        self._ed_import_geojson.setText(str(gj))

        if not self._ed_output.text():
            self._ed_output.setText(str(folder.parent / "annotations.geojson"))

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def _start(self):
        self._status.setText("")
        image_dir = Path(self._ed_image_dir.text().strip())
        shapefile = Path(self._ed_shapefile.text().strip())
        dem_path = Path(self._ed_dem.text().strip())
        cameras_xml = Path(self._ed_cameras.text().strip())
        output_path = Path(self._ed_output.text().strip())

        shx_text = self._ed_shx.text().strip()
        dbf_text = self._ed_dbf.text().strip()
        shx_path = Path(shx_text) if shx_text else None
        dbf_path = Path(dbf_text) if dbf_text else None

        # Validate
        errors = []
        if not image_dir.is_dir():
            errors.append("Image folder not found.")
        if not shapefile.is_file():
            errors.append("Shapefile not found.")
        if shx_path and not shx_path.is_file():
            errors.append(".shx file not found.")
        if dbf_path and not dbf_path.is_file():
            errors.append(".dbf file not found.")
        if not dem_path.is_file():
            errors.append("DEM file not found.")
        if not cameras_xml.is_file():
            errors.append("cameras.xml not found.")
        if not output_path.parent.exists():
            errors.append(f"Output directory does not exist: {output_path.parent}")

        if errors:
            self._status.setText(" | ".join(errors))
            return

        self._btn_start.setText("Loading…")
        self._btn_start.setEnabled(False)
        self.repaint()

        drone_model = "M4T" if self._rb_m4t.isChecked() else "M3T"

        # If .shx/.dbf are in a different folder, copy all sidecar files to a temp dir
        # alongside a copy of the .shp so geopandas can find them.
        self._shp_tempdir = None
        needs_copy = (shx_path and shx_path.parent != shapefile.parent) or \
                     (dbf_path and dbf_path.parent != shapefile.parent)
        if needs_copy:
            self._shp_tempdir = tempfile.mkdtemp()
            tmp = Path(self._shp_tempdir)
            shutil.copy2(shapefile, tmp / shapefile.name)
            src_shx = shx_path or shapefile.with_suffix(".shx")
            src_dbf = dbf_path or shapefile.with_suffix(".dbf")
            if src_shx.exists():
                shutil.copy2(src_shx, tmp / (shapefile.stem + ".shx"))
            if src_dbf.exists():
                shutil.copy2(src_dbf, tmp / (shapefile.stem + ".dbf"))
            prj = shapefile.with_suffix(".prj")
            if prj.exists():
                shutil.copy2(prj, tmp / prj.name)
            shapefile = tmp / shapefile.name

        try:
            project = load_project(image_dir, shapefile, dem_path, cameras_xml, output_path,
                                   drone_model=drone_model)
        except Exception as e:
            self._status.setText(f"Failed to load project: {e}")
            self._btn_start.setText("Start Annotation →")
            self._btn_start.setEnabled(True)
            return

        # Determine session/import to resume — explicit user selection takes priority.
        session_path = None
        session_text = self._ed_session.text().strip()
        import_text = self._ed_import_geojson.text().strip()
        if session_text and Path(session_text).is_file():
            session_path = ("session", Path(session_text))
        elif import_text and Path(import_text).is_file():
            session_path = ("geojson", Path(import_text))

        self._btn_start.setText("Start Annotation →")
        self._btn_start.setEnabled(True)

        # Persist to recent sessions
        session_file_str = self._ed_session.text().strip()
        if not session_file_str:
            # Use derived session path if it will be created
            session_file_str = str(project.session_file)
        entry = {
            "label": f"{image_dir.name} / {output_path.stem}",
            "image_dir": str(image_dir),
            "shapefile": self._ed_shapefile.text().strip(),
            "shx": self._ed_shx.text().strip(),
            "dbf": self._ed_dbf.text().strip(),
            "dem": str(dem_path),
            "cameras_xml": str(cameras_xml),
            "output_geojson": str(output_path),
            "session_file": session_file_str,
            "drone_model": drone_model,
        }
        save_recent(entry)
        # Refresh combo so this session appears at top
        self._recent_combo.blockSignals(True)
        self._recent_combo.clear()
        self._recent_combo.addItem("— select a recent session —", None)
        for e in load_recent():
            self._recent_combo.addItem(e.get("label", "?"), e)
        self._recent_combo.blockSignals(False)

        self.setup_complete.emit(project, session_path)
