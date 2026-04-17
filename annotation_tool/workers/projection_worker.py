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
            cached = self._cache.get(stem)
            if cached is not None:
                pixel_dict, delta_t_dict = cached
                # Retry any panels missing from delta_t_dict (handles partial failures)
                missing = {
                    idx: c for idx, c in pixel_dict.items() if idx not in delta_t_dict
                }
                if missing:
                    try:
                        from annotation_tool.data.projection_cache import _compute_delta_t
                        _compute_delta_t(
                            self._image_path, missing, delta_t_dict,
                            getattr(self._cache._project, "drone_model", "M3T"),
                        )
                        self._cache.put(stem, pixel_dict, delta_t_dict)
                    except Exception as e:
                        print(f"delta_t retry failed for {stem}: {e}")
            else:
                pixel_dict, delta_t_dict = self._cache.compute(self._image_path)
                self._cache.put(stem, pixel_dict, delta_t_dict)
            self.finished.emit(stem, pixel_dict, delta_t_dict)
        except Exception as e:
            self.error.emit(stem, str(e))
