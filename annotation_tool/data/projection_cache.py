"""Per-image polygon projection cache (disk .npz + in-memory LRU)."""

from __future__ import annotations

import pickle
from collections import OrderedDict
from pathlib import Path
from math import cos, radians

import numpy as np

DENSIFY = 8  # ring interpolation factor (matches extractor.py)
MAX_MEMORY_ENTRIES = 10


class ProjectionCache:
    """Cache projected pixel coordinates for each image.

    Results are stored as:
      - In-memory LRU dict (up to MAX_MEMORY_ENTRIES images)
      - Disk .pkl file per image in <image_dir>/.projection_cache/

    Each cache entry is a tuple of two dicts:
      pixel_dict:   {shp_index: [(u, v), ...]}   (screen pixel coords)
      delta_t_dict: {shp_index: float}            (ΔT in Celsius, may be empty)
    """

    def __init__(self, project):
        self._project = project
        self._cache_dir = project.image_dir / ".projection_cache"
        self._cache_dir.mkdir(exist_ok=True)
        self._memory: OrderedDict[str, tuple[dict, dict]] = OrderedDict()

    def get(self, stem: str) -> tuple[dict, dict] | None:
        if stem in self._memory:
            self._memory.move_to_end(stem)
            return self._memory[stem]
        disk_path = self._cache_dir / f"{stem}.pkl"
        if disk_path.exists():
            try:
                with open(disk_path, "rb") as f:
                    result = pickle.load(f)
                self._put_memory(stem, result)
                return result
            except Exception:
                disk_path.unlink(missing_ok=True)
        return None

    def put(self, stem: str, pixel_dict: dict, delta_t_dict: dict):
        result = (pixel_dict, delta_t_dict)
        self._put_memory(stem, result)
        disk_path = self._cache_dir / f"{stem}.pkl"
        try:
            with open(disk_path, "wb") as f:
                pickle.dump(result, f, protocol=4)
        except Exception:
            pass

    def _put_memory(self, stem: str, result: tuple):
        self._memory[stem] = result
        self._memory.move_to_end(stem)
        while len(self._memory) > MAX_MEMORY_ENTRIES:
            self._memory.popitem(last=False)

    def compute(self, image_path: Path) -> tuple[dict, dict]:
        """Project all visible polygons for image_path. Returns (pixel_dict, delta_t_dict)."""
        project = self._project
        model = project.model
        dem = project.dem
        geoms = project.geoms
        sindex = project.sindex

        from extractor import (
            make_metashape_projector, DemSampler,
            _camera_position_lla, _compute_footprint_bbox, _centroid_in_mask,
        )

        pose = model.cameras.get(image_path.stem) if model else None
        if pose is None:
            return {}, {}

        intr = model.sensors.get(pose.sensor_id)
        if intr is None:
            return {}, {}

        # Use vertical_offset=0.0 to match extractor.py's metashape path (line 659)
        dem_for_image = DemSampler(
            dem.array, dem.transform, dem.nodata, dem.mean_fallback,
            vertical_offset=0.0
        )

        projector = make_metashape_projector(pose, intr, model)
        cam_lat, cam_lon, cam_alt = _camera_position_lla(pose, model)

        footprint = _compute_footprint_bbox(projector, cam_lat, cam_lon, cam_alt, dem_for_image)
        candidate_idx = sindex.query(footprint, predicate="intersects")

        pixel_dict: dict[int, list[tuple[float, float]]] = {}

        for arr_idx in candidate_idx:
            geom = geoms[arr_idx]
            if not _centroid_in_mask(geom, projector, dem_for_image):
                continue

            polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
            all_px: list[tuple[float, float]] = []
            for poly in polys:
                px = _densify_ring_to_px(poly.exterior.coords, projector, dem_for_image)
                if px and len(px) >= 3:
                    all_px.extend(px)
                    all_px.append(None)  # sentinel to separate sub-polygons

            if all_px:
                pixel_dict[int(arr_idx)] = all_px

        # ΔT computation (requires DJI SDK — graceful fallback)
        delta_t_dict: dict[int, float] = {}
        try:
            _compute_delta_t(image_path, pixel_dict, delta_t_dict,
                             getattr(project, "drone_model", "M3T"))
        except Exception as e:
            print(f"delta_t compute failed for {image_path.name}: {e}")

        return pixel_dict, delta_t_dict


def _densify_ring_to_px(ring_coords, projector, dem) -> list[tuple[float, float]] | None:
    """Densify ring and project to pixel coords. Returns None if any vertex is behind camera."""
    pts = list(ring_coords)
    if len(pts) < 2:
        return None
    lons_list, lats_list = [], []
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        for k in range(DENSIFY):
            t = k / DENSIFY
            lons_list.append(x0 + t * (x1 - x0))
            lats_list.append(y0 + t * (y1 - y0))
    lons_a = np.array(lons_list, dtype=np.float64)
    lats_a = np.array(lats_list, dtype=np.float64)
    hs = dem(lons_a, lats_a)
    u, v, front = projector(lons_a, lats_a, hs)
    if not front.any():
        return None
    if not front.all():
        return None
    return list(zip(u.tolist(), v.tolist()))


def _compute_delta_t(image_path: Path, pixel_dict: dict, delta_t_dict: dict,
                     drone_model: str = "M3T"):
    """Compute ΔT (hotspot − surroundings) for each panel using thermal array."""
    import sys
    ROOT = Path(__file__).parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from dji_thermal import get_thermal_array

    thermal = get_thermal_array(str(image_path), drone_model)
    H, W = thermal.shape

    from PIL import Image, ImageDraw
    import numpy as np

    for shp_idx, coords in pixel_dict.items():
        # Build mask for this panel
        img_mask = Image.new("L", (W, H), 0)
        draw = ImageDraw.Draw(img_mask)
        # Filter out None sentinels and draw each sub-polygon
        sub_pts = []
        for pt in coords:
            if pt is None:
                if len(sub_pts) >= 3:
                    draw.polygon(sub_pts, fill=255)
                sub_pts = []
            else:
                sub_pts.append((int(round(pt[0])), int(round(pt[1]))))
        if len(sub_pts) >= 3:
            draw.polygon(sub_pts, fill=255)

        mask_arr = np.array(img_mask, dtype=bool)
        if not mask_arr.any():
            continue

        panel_temps = thermal[mask_arr]

        delta_t = float(panel_temps.max()) - float(panel_temps.min())
        delta_t_dict[shp_idx] = round(delta_t, 2)
