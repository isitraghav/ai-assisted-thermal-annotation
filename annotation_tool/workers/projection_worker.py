"""Background QThread for per-image polygon projection."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from annotation_tool.data.projection_cache import ProjectionCache


class ProjectionWorker(QThread):
    """Projects shapefile polygons onto a single image in a background thread.

    Emits finished(stem, pixel_dict, delta_t_dict) when done,
    or error(stem, message) on failure.
    """

    finished = pyqtSignal(str, dict, dict)
    error = pyqtSignal(str, str)

    def __init__(self, image_path: Path, cache: ProjectionCache, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._cache = cache

    def run(self):
        stem = self._image_path.stem
        try:
            # Check disk/memory cache first
            cached = self._cache.get(stem)
            if cached is not None:
                pixel_dict, delta_t_dict = cached
            else:
                pixel_dict, delta_t_dict = self._cache.compute(self._image_path)
                self._cache.put(stem, pixel_dict, delta_t_dict)
            self.finished.emit(stem, pixel_dict, delta_t_dict)
        except Exception as e:
            self.error.emit(stem, str(e))
