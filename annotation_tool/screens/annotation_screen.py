"""Main annotation workspace screen."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QShortcut, QMessageBox, QStatusBar,
)
from PyQt5.QtGui import QKeySequence

from annotation_tool.canvas.image_canvas import ImageCanvas
from annotation_tool.data.project import (
    ProjectState, AnnotationRecord, KEY_TO_ANOMALY,
)
from annotation_tool.data.projection_cache import ProjectionCache
from annotation_tool.data.session import SessionManager, HistoryEntry
from annotation_tool.widgets.annotation_panel import AnnotationPanel
from annotation_tool.widgets.image_navigator import ImageNavigator
from annotation_tool.workers.projection_worker import ProjectionWorker


class AnnotationScreen(QWidget):
    """Main annotation workspace.

    Layout:
        [ImageNavigator  — top bar spanning full width]
        [ImageCanvas  |  AnnotationPanel]
        [StatusBar    — bottom bar]
    """

    back_to_setup = pyqtSignal()

    def __init__(self, project: ProjectState, parent=None):
        super().__init__(parent)
        self._project = project
        self._cache = ProjectionCache(project)
        self._session = SessionManager(project, self._cache, parent=self)
        self._session.saved.connect(self._on_saved)

        # Track per-image projected data
        self._current_pixel_dict: dict = {}
        self._current_delta_t_dict: dict = {}

        # Workers: main + prefetch
        self._worker: ProjectionWorker | None = None
        self._prefetch_worker: ProjectionWorker | None = None

        self._setup_ui()
        self._setup_shortcuts()

        # Load first image
        if project.image_paths:
            self._navigate_to(project.current_image_idx)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def apply_session(self, session_info):
        """Load annotations from session or GeoJSON (called from app_window)."""
        if session_info is None:
            return
        kind, path = session_info
        if kind == "session":
            ok = self._session.load_session(path)
            if ok:
                idx = self._project.current_image_idx
                self._navigate_to(min(idx, len(self._project.image_paths) - 1))
                self._status_bar.showMessage(
                    f"Resumed session: {len(self._project.annotations)} annotations loaded."
                )
        elif kind == "geojson":
            ok = self._session.load_geojson(path)
            if ok:
                self._status_bar.showMessage(
                    f"Imported {len(self._project.annotations)} annotations from GeoJSON."
                )
            self._refresh_canvas_annotations()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar: navigator
        self._navigator = ImageNavigator(self)
        self._navigator.navigate.connect(self._navigate_to)
        layout.addWidget(self._navigator)

        # Center row: canvas + panel
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        self._canvas = ImageCanvas(self)
        self._canvas.polygon_clicked.connect(self._on_polygon_clicked)
        center.addWidget(self._canvas, stretch=1)

        self._panel = AnnotationPanel(self)
        self._panel.annotation_saved.connect(self._on_annotation_saved)
        self._panel.annotation_cleared.connect(self._on_annotation_cleared)
        center.addWidget(self._panel)

        layout.addLayout(center, stretch=1)

        # Status bar
        self._status_bar = QStatusBar(self)
        layout.addWidget(self._status_bar)
        self._status_bar.showMessage("Ready. Click a panel polygon to annotate.")

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def _setup_shortcuts(self):
        # Navigation
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self._next_image)
        QShortcut(QKeySequence(Qt.Key_Left),  self).activated.connect(self._prev_image)
        QShortcut(QKeySequence("D"),          self).activated.connect(self._next_image)
        QShortcut(QKeySequence("A"),          self).activated.connect(self._prev_image)

        # Annotation keys
        for key in list("1234567890") + ["s", "v", "S", "V"]:
            k = key
            QShortcut(QKeySequence(k), self).activated.connect(
                lambda _k=k.lower(): self._key_annotate(_k)
            )

        # Save / Clear
        QShortcut(QKeySequence(Qt.Key_Return), self).activated.connect(self._panel.trigger_save)
        QShortcut(QKeySequence(Qt.Key_Enter),  self).activated.connect(self._panel.trigger_save)
        QShortcut(QKeySequence(Qt.Key_Delete), self).activated.connect(self._clear_selected)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(self._deselect)

        # Undo / Redo
        QShortcut(QKeySequence("Ctrl+Z"),       self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Y"),        self).activated.connect(self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)

        # Save
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._session.save)

        # Zoom / fit
        QShortcut(QKeySequence("F"),   self).activated.connect(self._canvas.fit_view)
        QShortcut(QKeySequence("+"),   self).activated.connect(lambda: self._canvas.scale(1.15, 1.15))
        QShortcut(QKeySequence("="),   self).activated.connect(lambda: self._canvas.scale(1.15, 1.15))
        QShortcut(QKeySequence("-"),   self).activated.connect(lambda: self._canvas.scale(1/1.15, 1/1.15))

    def keyPressEvent(self, event):
        """Catch keys not grabbed by shortcuts (e.g. when canvas has focus)."""
        key = event.text().lower()
        if key in KEY_TO_ANOMALY:
            self._key_annotate(key)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate_to(self, idx: int):
        if not self._project.image_paths:
            return
        idx = max(0, min(idx, len(self._project.image_paths) - 1))
        self._project.current_image_idx = idx
        img_path = self._project.image_paths[idx]

        # Cancel existing worker if still running
        if self._worker and self._worker.isRunning():
            self._worker.finished.disconnect()
            self._worker.error.disconnect()
            self._worker.quit()
            self._worker.wait(500)

        self._canvas.load_image(img_path)
        self._update_navigator()

        # Launch projection worker
        self._worker = ProjectionWorker(img_path, self._cache, parent=self)
        self._worker.finished.connect(self._on_projection_done)
        self._worker.error.connect(self._on_projection_error)
        self._worker.start()

        # Prefetch next image
        self._launch_prefetch(idx + 1)

    def _next_image(self):
        self._navigate_to(self._project.current_image_idx + 1)

    def _prev_image(self):
        self._navigate_to(self._project.current_image_idx - 1)

    def _launch_prefetch(self, idx: int):
        if not (0 <= idx < len(self._project.image_paths)):
            return
        if self._prefetch_worker and self._prefetch_worker.isRunning():
            return
        path = self._project.image_paths[idx]
        if self._cache.get(path.stem) is not None:
            return
        self._prefetch_worker = ProjectionWorker(path, self._cache, parent=self)
        self._prefetch_worker.finished.connect(
            lambda s, pd, dt: None  # discard result; cache is already populated
        )
        self._prefetch_worker.start()

    # ------------------------------------------------------------------
    # Projection result
    # ------------------------------------------------------------------

    def _on_projection_done(self, stem: str, pixel_dict: dict, delta_t_dict: dict):
        # Only apply if this result matches the current image
        current_stem = self._project.image_paths[self._project.current_image_idx].stem
        if stem != current_stem:
            return
        self._current_pixel_dict = pixel_dict
        self._current_delta_t_dict = delta_t_dict
        self._canvas.populate_polygons(pixel_dict, self._project.annotations)
        n = len(pixel_dict)
        self._status_bar.showMessage(
            f"{self._project.image_paths[self._project.current_image_idx].name} — "
            f"{n} panel(s) visible"
        )

    def _on_projection_error(self, stem: str, msg: str):
        current_stem = self._project.image_paths[self._project.current_image_idx].stem
        if stem == current_stem:
            self._status_bar.showMessage(f"Projection error: {msg}")

    # ------------------------------------------------------------------
    # Polygon selection
    # ------------------------------------------------------------------

    def _on_polygon_clicked(self, shp_idx: int):
        coords = self._current_pixel_dict.get(shp_idx, [])
        existing_rec = self._project.annotations.get(shp_idx)
        img_path = self._project.image_paths[self._project.current_image_idx]

        date_str, time_str = _extract_exif_datetime(img_path)
        delta_t = self._current_delta_t_dict.get(shp_idx)

        # Get centroid from shapefile
        geom = self._project.gdf.geometry.iloc[shp_idx]
        lon, lat = geom.centroid.x, geom.centroid.y

        # Try to get rack/panel from shapefile columns
        row = self._project.gdf.iloc[shp_idx]
        auto_rack = str(row.get("Rack", "")) if hasattr(row, "get") else ""
        auto_panel = str(row.get("Panel", "")) if hasattr(row, "get") else ""
        auto_module = str(row.get("Module", "")) if hasattr(row, "get") else ""
        auto_row = str(row.get("row", "")) if hasattr(row, "get") else ""
        auto_col = str(row.get("col", "")) if hasattr(row, "get") else ""
        try:
            auto_rack = str(row["Rack"]) if "Rack" in row.index else ""
            auto_panel = str(row["Panel"]) if "Panel" in row.index else ""
            auto_module = str(row["Module"]) if "Module" in row.index else ""
            auto_row = str(row["row"]) if "row" in row.index else ""
            auto_col = str(row["col"]) if "col" in row.index else ""
        except Exception:
            pass

        self._panel.load_polygon(
            shp_index=shp_idx,
            pixel_coords=coords,
            existing_rec=existing_rec,
            auto_date=date_str,
            auto_time=time_str,
            auto_delta_t=delta_t,
            auto_lon=lon,
            auto_lat=lat,
            auto_rack=auto_rack,
            auto_panel=auto_panel,
            auto_module=auto_module,
            auto_row=auto_row,
            auto_col=auto_col,
        )
        self._status_bar.showMessage(
            f"Selected panel #{shp_idx} — fill in properties and press Enter or a number key."
        )

    # ------------------------------------------------------------------
    # Annotation save/clear
    # ------------------------------------------------------------------

    def _on_annotation_saved(self, rec: AnnotationRecord):
        img_path = self._project.image_paths[self._project.current_image_idx]
        rec.image_name = img_path.name

        shp_idx = rec.shp_index
        before = self._project.annotations.get(shp_idx)
        entry = HistoryEntry(shp_index=shp_idx, before=before, after=rec)
        self._session.push(entry)

        self._canvas.update_polygon_state(shp_idx, rec.anomaly)
        coords = self._current_pixel_dict.get(shp_idx, [])
        self._canvas.add_or_update_marker(shp_idx, coords)
        self._update_navigator()
        self._status_bar.showMessage(
            f"Annotated panel #{shp_idx} as '{rec.anomaly}'. "
            f"Total: {len(self._project.annotations)}"
        )

    def _on_annotation_cleared(self, shp_idx: int):
        before = self._project.annotations.get(shp_idx)
        if before is None:
            return
        entry = HistoryEntry(shp_index=shp_idx, before=before, after=None)
        self._session.push(entry)
        self._canvas.update_polygon_state(shp_idx, None)
        self._canvas.remove_marker(shp_idx)
        self._panel.clear_selection()
        self._canvas.deselect()
        self._update_navigator()
        self._status_bar.showMessage(f"Cleared annotation for panel #{shp_idx}.")

    def _clear_selected(self):
        shp_idx = self._canvas.get_selected_shp_index()
        if shp_idx is not None:
            self._on_annotation_cleared(shp_idx)

    def _deselect(self):
        self._canvas.deselect()
        self._panel.clear_selection()

    def _key_annotate(self, key: str):
        """Set anomaly type by key and immediately save if a polygon is selected."""
        if self._panel.set_anomaly_by_key(key):
            if self._canvas.get_selected_shp_index() is not None:
                self._panel.trigger_save()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _undo(self):
        entry = self._session.undo()
        if entry:
            self._refresh_after_history(entry)
            self._status_bar.showMessage(f"Undo: panel #{entry.shp_index}")

    def _redo(self):
        entry = self._session.redo()
        if entry:
            self._refresh_after_history(entry)
            self._status_bar.showMessage(f"Redo: panel #{entry.shp_index}")

    def _refresh_after_history(self, entry: HistoryEntry):
        shp_idx = entry.shp_index
        rec = self._project.annotations.get(shp_idx)
        anomaly = rec.anomaly if rec else None
        self._canvas.update_polygon_state(shp_idx, anomaly)
        if rec and shp_idx in self._current_pixel_dict:
            self._canvas.add_or_update_marker(shp_idx, self._current_pixel_dict[shp_idx])
        else:
            self._canvas.remove_marker(shp_idx)
        self._update_navigator()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_canvas_annotations(self):
        """Redraw all polygon states from current project.annotations."""
        for shp_idx, rec in self._project.annotations.items():
            self._canvas.update_polygon_state(shp_idx, rec.anomaly)
            if shp_idx in self._current_pixel_dict:
                self._canvas.add_or_update_marker(
                    shp_idx, self._current_pixel_dict[shp_idx]
                )
        self._update_navigator()

    def _update_navigator(self):
        idx = self._project.current_image_idx
        total = len(self._project.image_paths)
        filename = self._project.image_paths[idx].name if self._project.image_paths else ""
        self._navigator.set_state(
            current=idx,
            total=total,
            filename=filename,
            annotated=len(self._project.annotations),
        )

    def _on_saved(self, msg: str):
        self._status_bar.showMessage(msg)


# ------------------------------------------------------------------
# EXIF helpers
# ------------------------------------------------------------------

def _extract_exif_datetime(image_path: Path) -> tuple[str, str]:
    """Return (date_str, time_str) from EXIF. Graceful fallback."""
    try:
        import piexif
        raw = image_path.read_bytes()
        exif_data = piexif.load(raw)
        dt_bytes = exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if dt_bytes:
            dt_str = dt_bytes.decode("ascii", errors="replace")
            # Format: "2026:03:31 14:02:28"
            parts = dt_str.strip().split(" ")
            if len(parts) == 2:
                date_part = parts[0].replace(":", "/")
                # Reformat from YYYY/MM/DD to MM/DD/YYYY
                dp = date_part.split("/")
                if len(dp) == 3:
                    date_part = f"{dp[1]}/{dp[2]}/{dp[0]}"
                time_part = parts[1]
                # Convert to AM/PM
                th = time_part.split(":")
                if len(th) == 3:
                    h = int(th[0])
                    m = th[1]
                    s = th[2]
                    suffix = "AM" if h < 12 else "PM"
                    h12 = h % 12 or 12
                    time_part = f"{h12}:{m}:{s} {suffix}"
                return date_part, time_part
    except Exception:
        pass
    return "", ""
