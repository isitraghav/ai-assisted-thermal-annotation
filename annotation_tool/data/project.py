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
    "Bypass Diode",
    "Cell",
    "Dust",
    "Module Missing",
    "Module Offline",
    "Multi Cell",
    "Partial String Offline",
    "Physical Damage",
    "Shading",
    "Short Circuit",
    "String Offline",
    "Vegetation",
]

# Maps number/letter keys to anomaly type
KEY_TO_ANOMALY: dict[str, str] = {
    "1": "Bypass Diode",
    "2": "Cell",
    "3": "Dust",
    "4": "Module Missing",
    "5": "Module Offline",
    "6": "Multi Cell",
    "7": "Partial String Offline",
    "8": "Physical Damage",
    "9": "Shading",
    "0": "String Offline",
    "s": "Short Circuit",
    "v": "Vegetation",
}


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


def load_project(
    image_dir: Path,
    shapefile: Path,
    dem_path: Path,
    cameras_xml: Path,
    output_geojson: Path,
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

    # Collect images
    image_paths = sorted(
        list(image_dir.glob("*.JPG")) + list(image_dir.glob("*.jpg"))
    )

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
    )
