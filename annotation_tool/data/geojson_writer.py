"""GeoJSON serializer for annotation records.

Output matches the schema of the existing 1775925810686-report.geojson exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import shapely.geometry

from annotation_tool.data.project import AnnotationRecord, exported_image_name


class GeoJSONWriter:
    @staticmethod
    def write(
        annotations: dict[int, AnnotationRecord],
        gdf: gpd.GeoDataFrame,
        output_path: Path,
    ):
        features = []
        for i, (shp_idx, rec) in enumerate(sorted(annotations.items()), start=1):
            geom = gdf.geometry.iloc[shp_idx]

            # Always output as MultiPolygon to match existing report format
            if geom.geom_type == "Polygon":
                coords = [[list(map(list, geom.exterior.coords))]]
                geom_dict = {"type": "MultiPolygon", "coordinates": [coords]}
            elif geom.geom_type == "MultiPolygon":
                geom_dict = shapely.geometry.mapping(geom)
            else:
                geom_dict = shapely.geometry.mapping(geom)

            feature = {
                "type": "Feature",
                "geometry": geom_dict,
                "properties": {
                    "Anomaly": rec.anomaly,
                    "Longitude": str(rec.longitude),
                    "Latitude": str(rec.latitude),
                    "Date": rec.date,
                    "Time": rec.time,
                    "Image name": exported_image_name(rec),
                    "Hotspot": str(rec.delta_t),
                    "Block": rec.block,
                    "ID": rec.panel_id_full,
                    "Rack": rec.rack,
                    "Panel": rec.panel,
                    "Module": rec.module,
                    "row": rec.row,
                    "col": rec.col,
                    "Make": "",
                    "Watt": "",
                    "pixel_coords": rec.pixel_coords,
                    "name": str(i),
                },
            }
            features.append(feature)

        geojson = {
            "type": "FeatureCollection",
            "name": "report",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": features,
        }
        output_path.write_text(json.dumps(geojson, indent=2))
