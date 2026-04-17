"""Export annotation records to CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from annotation_tool.data.project import AnnotationRecord, exported_image_name

_FIELDS = [
    "#", "Anomaly", "Rack", "Panel", "Module", "Block", "Full ID",
    "Date", "Time", "Delta T (C)", "Longitude", "Latitude",
    "Image Name", "Row", "Col",
]


def export_csv(annotations: dict[int, AnnotationRecord], output_path: Path):
    rows = []
    for i, (_, rec) in enumerate(sorted(annotations.items()), start=1):
        rows.append({
            "#": i,
            "Anomaly": rec.anomaly,
            "Rack": rec.rack,
            "Panel": rec.panel,
            "Module": rec.module,
            "Block": rec.block,
            "Full ID": rec.panel_id_full,
            "Date": rec.date,
            "Time": rec.time,
            "Delta T (C)": rec.delta_t,
            "Longitude": rec.longitude,
            "Latitude": rec.latitude,
            "Image Name": exported_image_name(rec),
            "Row": rec.row,
            "Col": rec.col,
        })
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
