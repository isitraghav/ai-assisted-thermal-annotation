"""ProjectState dataclass and AnnotationRecord."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

# Parent-directory imports happen AFTER sys.path is patched in main.py
# (imported here only for type hints that are resolved at runtime)


ANOMALY_TYPES = [
    "None",
    "Cell",
    "Multi Cell",
    "Bypass Diode",
    "Module Offline",
    "Module Missing",
    "Partial String Offline",
    "Physical Damage",
    "Shading",
    "Short Circuit",
    "String Offline",
    "Vegetation",
    "Dust",
]

# Maps number/letter keys to anomaly type
KEY_TO_ANOMALY: dict[str, str] = {
    "1": "Cell",
    "2": "Multi Cell",
    "3": "Bypass Diode",
    "4": "Module Offline",
    "5": "Module Missing",
    "6": "Partial String Offline",
    "7": "Physical Damage",
    "8": "Shading",
    "9": "Short Circuit",
    "0": "String Offline",
    "s": "Short Circuit",
    "v": "Vegetation",
    "d": "Dust",
}


def exported_image_name(rec: "AnnotationRecord") -> str:
    """Return the exported filename for an annotation, e.g. DJI_0001_R1_P3_Cell.jpg.

    Used by both image_exporter and geojson_writer to keep names consistent.
    """
    from pathlib import Path as _Path
    stem = _Path(rec.image_name).stem
    parts = [rec.rack, rec.panel, rec.anomaly.replace(" ", "_")]
    label = "_".join(p for p in parts if p)
    return f"{stem}_{label}.jpg" if label else f"{stem}.jpg"


@dataclass
class AnnotationRecord:
    shp_index: int
    anomaly: str
    rack: str
    panel: str
    module: str
    row: str
    col: str
    image_name: str
    date: str          # "MM/DD/YYYY"
    time: str          # "H:MM:SS AM/PM"
    delta_t: float
    longitude: float
    latitude: float
    block: str = ""
    panel_id_full: str = ""
    pixel_coords: list = None

    def to_dict(self) -> dict:
        return {
            "shp_index": self.shp_index,
            "anomaly": self.anomaly,
            "rack": self.rack,
            "panel": self.panel,
            "module": self.module,
            "row": self.row,
            "col": self.col,
            "image_name": self.image_name,
            "date": self.date,
            "time": self.time,
            "delta_t": self.delta_t,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "block": self.block,
            "panel_id_full": self.panel_id_full,
            "pixel_coords": self.pixel_coords or [],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnnotationRecord":
        return cls(
            shp_index=int(d["shp_index"]),
            anomaly=d.get("anomaly", ""),
            rack=d.get("rack", ""),
            panel=d.get("panel", ""),
            module=d.get("module", ""),
            row=d.get("row", ""),
            col=d.get("col", ""),
            image_name=d.get("image_name", ""),
            date=d.get("date", ""),
            time=d.get("time", ""),
            delta_t=float(d.get("delta_t", 0.0)),
            longitude=float(d.get("longitude", 0.0)),
            latitude=float(d.get("latitude", 0.0)),
            block=d.get("block", ""),
            panel_id_full=d.get("panel_id_full", ""),
            pixel_coords=d.get("pixel_coords", []),
        )


@dataclass
class ProjectState:
    image_dir: Path
    shapefile: Path
    dem_path: Path
    cameras_xml: Path
    output_geojson: Path
    session_file: Path

    # Loaded data (populated by load_project())
    model: object = None          # MetashapeModel
    dem: object = None            # DemSampler
    gdf: gpd.GeoDataFrame = None
    geoms: np.ndarray = None
    sindex: object = None

    image_paths: list = field(default_factory=list)
    current_image_idx: int = 0

    annotations: dict = field(default_factory=dict)  # shp_index → AnnotationRecord

    drone_model: str = "M3T"


def load_project(
    image_dir: Path,
    shapefile: Path,
    dem_path: Path,
    cameras_xml: Path,
    output_geojson: Path,
    drone_model: str = "M3T",
) -> ProjectState:
    """Load all project data and return a ProjectState."""
    # These imports are available after main.py patches sys.path
    from extractor import (
        DemSampler, load_metashape_model, DEM_MEAN_FALLBACK
    )

    session_file = output_geojson.with_suffix(".session.json")

    # Load shapefile
    gdf = gpd.read_file(shapefile)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    geoms = gdf.geometry.values
    sindex = gdf.sindex

    # Load DEM
    with rasterio.open(dem_path) as src:
        array = src.read(1)
        transform = src.transform
        nodata = src.nodata
    dem = DemSampler(
        array=array,
        transform=transform,
        nodata=nodata,
        mean_fallback=DEM_MEAN_FALLBACK,
        vertical_offset=0.0,
    )

    # Load Metashape model
    model = load_metashape_model(cameras_xml)

    # Collect images (deduplicate in case .JPG and .jpg resolve to same file)
    _raw = sorted(list(image_dir.glob("*.JPG")) + list(image_dir.glob("*.jpg")))
    image_paths = [Path(p) for p in dict.fromkeys(str(p) for p in _raw)]

    return ProjectState(
        image_dir=image_dir,
        shapefile=shapefile,
        dem_path=dem_path,
        cameras_xml=cameras_xml,
        output_geojson=output_geojson,
        session_file=session_file,
        model=model,
        dem=dem,
        gdf=gdf,
        geoms=geoms,
        sindex=sindex,
        image_paths=image_paths,
        current_image_idx=0,
        annotations={},
        drone_model=drone_model,
    )
