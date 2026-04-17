"""Incremental YOLO segmentation training dataset exporter."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from annotation_tool.data.project import ANOMALY_TYPES, AnnotationRecord

_CLASSES = [
    "cell",
    "multi_cell",
    "bypass_diode",
    "module_offline",
    "module_missing",
    "partial_string_offline",
    "physical_damage",
    "shading",
    "short_circuit",
    "string_offline",
    "vegetation",
    "dust",
]

_ANOMALY_TO_CLASS_IDX: dict[str, int] = {
    "Cell": 0,
    "Multi Cell": 1,
    "Bypass Diode": 2,
    "Module Offline": 3,
    "Module Missing": 4,
    "Partial String Offline": 5,
    "Physical Damage": 6,
    "Shading": 7,
    "Short Circuit": 8,
    "String Offline": 9,
    "Vegetation": 10,
    "Dust": 11,
}

_CLASS_TO_IDX = _ANOMALY_TO_CLASS_IDX


class TrainingExporter:
    """Writes/updates training_dataset/ after each save.

    Layout (next to output_geojson):
        training_dataset/
        ├── dataset.yaml
        ├── classes.txt
        ├── images/train/<name>.jpg   (copied once, never overwritten)
        └── labels/train/<name>.txt   (rewritten each save for current session images)
    """

    CLASSES = _CLASSES
    CLASS_TO_IDX = _CLASS_TO_IDX

    def __init__(self, training_dir: Path) -> None:
        self._dir = training_dir
        self._images_dir = training_dir / "images" / "train"
        self._labels_dir = training_dir / "labels" / "train"
        self._size_cache: dict[str, tuple[int, int]] = {}

    def export(
        self,
        annotations: dict[int, AnnotationRecord],
        image_paths_by_name: dict[str, Path],
    ) -> None:
        self._images_dir.mkdir(parents=True, exist_ok=True)
        self._labels_dir.mkdir(parents=True, exist_ok=True)

        by_image: dict[str, list[AnnotationRecord]] = {}
        for rec in annotations.values():
            if rec.image_name:
                by_image.setdefault(rec.image_name, []).append(rec)

        for image_name, recs in by_image.items():
            src_path = image_paths_by_name.get(image_name)

            dst_img = self._images_dir / image_name
            if src_path and src_path.exists() and not dst_img.exists():
                shutil.copy2(src_path, dst_img)

            w, h = self._get_image_size_cached(image_name, src_path, dst_img)

            label_path = self._labels_dir / (Path(image_name).stem + ".txt")
            lines: list[str] = []
            for rec in recs:
                if not rec.pixel_coords:
                    continue
                if rec.anomaly == "None":
                    continue
                class_idx = self.CLASS_TO_IDX.get(rec.anomaly)
                if class_idx is None:
                    continue
                if w is None or h is None:
                    continue
                normalized = self._normalize_coords(rec.pixel_coords, w, h)
                if len(normalized) < 6:
                    continue
                coords_str = " ".join(f"{v:.6f}" for v in normalized)
                lines.append(f"{class_idx} {coords_str}")

            label_path.write_text("\n".join(lines) + ("\n" if lines else ""))

        self._write_dataset_yaml()
        self._write_classes_txt()

    def _get_image_size_cached(
        self, key: str, src_path: Optional[Path], dst_path: Path
    ) -> tuple[Optional[int], Optional[int]]:
        if key in self._size_cache:
            return self._size_cache[key]
        w, h = self._get_image_size(src_path)
        if (w is None or h is None) and dst_path.exists():
            w, h = self._get_image_size(dst_path)
        if w is not None and h is not None:
            self._size_cache[key] = (w, h)
        return w, h

    def _get_image_size(
        self, img_path: Optional[Path]
    ) -> tuple[Optional[int], Optional[int]]:
        if img_path is None or not img_path.exists():
            return None, None
        try:
            from PIL import Image
            with Image.open(img_path) as img:
                return img.width, img.height
        except Exception:
            return None, None

    def _normalize_coords(
        self, pixel_coords: list, w: int, h: int
    ) -> list[float]:
        result: list[float] = []
        for pt in pixel_coords:
            if pt is None:
                continue
            u, v = float(pt[0]), float(pt[1])
            result.append(max(0.0, min(1.0, u / w)))
            result.append(max(0.0, min(1.0, v / h)))
        return result

    def _write_dataset_yaml(self) -> None:
        abs_path = str(self._dir.resolve())
        names_block = "\n".join(
            f"  {i}: {name}" for i, name in enumerate(self.CLASSES)
        )
        content = (
            f"path: {abs_path}\n"
            f"train: images/train\n"
            f"val: images/train  # same dir, split manually if needed\n"
            f"names:\n"
            f"{names_block}\n"
        )
        (self._dir / "dataset.yaml").write_text(content)

    def _write_classes_txt(self) -> None:
        (self._dir / "classes.txt").write_text("\n".join(self.CLASSES) + "\n")
