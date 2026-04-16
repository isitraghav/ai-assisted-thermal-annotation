"""SessionManager: undo/redo stack, auto-save, resume."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from annotation_tool.data.project import AnnotationRecord, ProjectState
from annotation_tool.data.geojson_writer import GeoJSONWriter
from annotation_tool.data.image_exporter import export_annotated_images
from annotation_tool.data.training_exporter import TrainingExporter

MAX_UNDO = 500


@dataclass
class HistoryEntry:
    shp_index: int
    before: Optional[AnnotationRecord]
    after: Optional[AnnotationRecord]


class SessionManager(QObject):
    changed = pyqtSignal()        # emitted after any undo/redo/push
    saved = pyqtSignal(str)       # emitted with status message after save

    def __init__(self, project: ProjectState, cache, parent=None):
        super().__init__(parent)
        self._project = project
        self._cache = cache
        self._undo_stack: list[HistoryEntry] = []
        self._redo_stack: list[HistoryEntry] = []
        self._dirty = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self.save)

        training_dir = project.output_geojson.parent / "training_dataset"
        self._training_exporter = TrainingExporter(training_dir)
        self._image_paths_by_name: dict[str, Path] = {
            p.name: p for p in project.image_paths
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, entry: HistoryEntry):
        """Record a new annotation action and clear redo stack."""
        # Apply the 'after' state to project annotations
        if entry.after is None:
            self._project.annotations.pop(entry.shp_index, None)
        else:
            self._project.annotations[entry.shp_index] = entry.after

        self._undo_stack.append(entry)
        self._redo_stack.clear()
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self.mark_dirty()
        self.changed.emit()

    def undo(self) -> Optional[HistoryEntry]:
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        self._redo_stack.append(entry)
        # Restore 'before' state
        if entry.before is None:
            self._project.annotations.pop(entry.shp_index, None)
        else:
            self._project.annotations[entry.shp_index] = entry.before
        self.mark_dirty()
        self.changed.emit()
        return entry

    def redo(self) -> Optional[HistoryEntry]:
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        self._undo_stack.append(entry)
        # Re-apply 'after' state
        if entry.after is None:
            self._project.annotations.pop(entry.shp_index, None)
        else:
            self._project.annotations[entry.shp_index] = entry.after
        self.mark_dirty()
        self.changed.emit()
        return entry

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def save(self):
        """Force save GeoJSON + session file + annotated images."""
        try:
            GeoJSONWriter.write(
                self._project.annotations,
                self._project.gdf,
                self._project.output_geojson,
            )
            self._save_session_json()
            n_img = export_annotated_images(self._project, self._cache)
            try:
                self._training_exporter.export(
                    self._project.annotations,
                    self._image_paths_by_name,
                )
            except Exception as te:
                print(f"Training export warning: {te}")
            self._dirty = False
            n = len(self._project.annotations)
            self.saved.emit(
                f"Saved {n} annotation(s) → {self._project.output_geojson.name}"
                + (f"  |  {n_img} image(s) exported" if n_img else "")
            )
        except Exception as e:
            self.saved.emit(f"Save failed: {e}")

    def load_session(self, session_path: Path) -> bool:
        """Restore annotations from a session .json file. Returns True on success."""
        try:
            with open(session_path) as f:
                data = json.load(f)
            annotations = {}
            for k, v in data.get("annotations", {}).items():
                rec = AnnotationRecord.from_dict(v)
                annotations[rec.shp_index] = rec
            self._project.annotations = annotations
            self._project.current_image_idx = int(data.get("last_image_idx", 0))
            self._undo_stack.clear()
            self._redo_stack.clear()
            self.changed.emit()
            return True
        except Exception as e:
            print(f"Failed to load session: {e}")
            return False

    def load_geojson(self, geojson_path: Path) -> bool:
        """Import annotations from an existing GeoJSON report via spatial join."""
        try:
            import geopandas as gpd
            import shapely

            imported = gpd.read_file(geojson_path)
            if imported.crs is None or imported.crs.to_epsg() != 4326:
                try:
                    imported = imported.set_crs(epsg=4326, allow_override=True)
                except Exception:
                    pass

            gdf = self._project.gdf
            annotations = {}

            for _, feat in imported.iterrows():
                # Match to shapefile polygon by spatial overlap
                centroid = feat.geometry.centroid
                candidates = list(self._project.sindex.query(
                    shapely.box(
                        centroid.x - 0.0001, centroid.y - 0.0001,
                        centroid.x + 0.0001, centroid.y + 0.0001,
                    ),
                    predicate="intersects"
                ))
                best_idx = None
                best_overlap = 0.0
                for ci in candidates:
                    try:
                        overlap = feat.geometry.intersection(gdf.geometry.iloc[ci]).area
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_idx = int(ci)
                    except Exception:
                        continue

                if best_idx is None:
                    continue

                props = feat if not hasattr(feat, "to_dict") else feat
                lon = float(props.get("Longitude", 0) or 0)
                lat = float(props.get("Latitude", 0) or 0)
                try:
                    lon = float(props["Longitude"])
                    lat = float(props["Latitude"])
                except Exception:
                    cent = gdf.geometry.iloc[best_idx].centroid
                    lon, lat = cent.x, cent.y

                rec = AnnotationRecord(
                    shp_index=best_idx,
                    anomaly=str(props.get("Anomaly", "")),
                    rack=str(props.get("Rack", "")),
                    panel=str(props.get("Panel", "")),
                    module=str(props.get("Module", "")),
                    row=str(props.get("row", "")),
                    col=str(props.get("col", "")),
                    image_name=str(props.get("Image name", props.get("image_name", ""))),
                    date=str(props.get("Date", "")),
                    time=str(props.get("Time", "")),
                    delta_t=float(props.get("Hotspot", props.get("delta_t", 0)) or 0),
                    longitude=lon,
                    latitude=lat,
                    block=str(props.get("Block", "")),
                    panel_id_full=str(props.get("ID", props.get("panel_id_full", ""))),
                )
                annotations[best_idx] = rec

            self._project.annotations = annotations
            self._undo_stack.clear()
            self._redo_stack.clear()
            self.changed.emit()
            return True
        except Exception as e:
            print(f"Failed to import GeoJSON: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def mark_dirty(self):
        self._dirty = True
        self._autosave_timer.start()

    def _save_session_json(self):
        data = {
            "version": 1,
            "image_dir": str(self._project.image_dir),
            "shapefile": str(self._project.shapefile),
            "dem": str(self._project.dem_path),
            "cameras_xml": str(self._project.cameras_xml),
            "output_geojson": str(self._project.output_geojson),
            "last_image_idx": self._project.current_image_idx,
            "annotations": {
                str(k): v.to_dict()
                for k, v in self._project.annotations.items()
            },
        }
        with open(self._project.session_file, "w") as f:
            json.dump(data, f, indent=2)
