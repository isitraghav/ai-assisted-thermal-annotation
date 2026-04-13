"""Setup screen: file/folder selection before starting annotation."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QFileDialog,
    QMessageBox, QFrame,
)

from annotation_tool.data.project import load_project, ProjectState


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
        files_layout.addRow("Shapefile:", self._make_browse_row(
            self._ed_shapefile, self._browse_shapefile
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

    def _browse_image_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select image folder")
        if d:
            self._ed_image_dir.setText(d)
            self._autodetect_from_dir(Path(d))

    def _browse_shapefile(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select shapefile", filter="Shapefiles (*.shp)")
        if f:
            self._ed_shapefile.setText(f)

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
        # Search folder and parent for common files
        search_dirs = [folder, folder.parent]
        for sd in search_dirs:
            shps = list(sd.glob("*.shp"))
            if shps and not self._ed_shapefile.text():
                self._ed_shapefile.setText(str(shps[0]))

            tifs = list(sd.glob("*.tif")) + list(sd.glob("*.tiff"))
            tifs = [t for t in tifs if "dem" in t.name.lower() or "DEM" in t.name]
            if not tifs:
                tifs = list(sd.glob("DEM.tif")) + list(sd.glob("DEM.tiff"))
            if tifs and not self._ed_dem.text():
                self._ed_dem.setText(str(tifs[0]))

            xmls = list(sd.glob("cameras.xml"))
            if xmls and not self._ed_cameras.text():
                self._ed_cameras.setText(str(xmls[0]))

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

        # Validate
        errors = []
        if not image_dir.is_dir():
            errors.append("Image folder not found.")
        if not shapefile.is_file():
            errors.append("Shapefile not found.")
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

        try:
            project = load_project(image_dir, shapefile, dem_path, cameras_xml, output_path)
        except Exception as e:
            self._status.setText(f"Failed to load project: {e}")
            self._btn_start.setText("Start Annotation →")
            self._btn_start.setEnabled(True)
            return

        # Auto-resume session if one exists for this project, otherwise
        # fall back to a manually imported GeoJSON (if provided).
        session_path = None
        if project.session_file.is_file():
            session_path = ("session", project.session_file)
        else:
            import_text = self._ed_import_geojson.text().strip()
            if import_text and Path(import_text).is_file():
                session_path = ("geojson", Path(import_text))

        self._btn_start.setText("Start Annotation →")
        self._btn_start.setEnabled(True)
        self.setup_complete.emit(project, session_path)
