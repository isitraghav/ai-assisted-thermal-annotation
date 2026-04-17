"""Export thermal images with polygon overlays to annotated_images/."""

from __future__ import annotations

import shutil
from pathlib import Path

from annotation_tool.data.project import ProjectState, exported_image_name

_LINE_WIDTH = 2


def _split_subpolygons(coords: list) -> list[list[tuple[float, float]]]:
    """Split a flat coord list at None separators into sub-polygon lists."""
    polys, current = [], []
    for pt in coords:
        if pt is None:
            if len(current) >= 3:
                polys.append(current)
            current = []
        else:
            current.append((float(pt[0]), float(pt[1])))
    if len(current) >= 3:
        polys.append(current)
    return polys or []




def _cleanup_orphaned_images(out_dir: Path, valid_names: set[str]):
    deleted_dir = out_dir.parent / "deleted_markings"
    deleted_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.jpg"):
        if f.name not in valid_names:
            dest = deleted_dir / f.name
            # avoid collision in deleted_markings
            if dest.exists():
                stem, ext = f.stem, f.suffix
                counter = 1
                while dest.exists():
                    dest = deleted_dir / f"{stem}_{counter}{ext}"
                    counter += 1
            shutil.move(str(f), dest)


def export_annotated_images(
    project: ProjectState,
    cache,
    dirty_indices: set[int] | None = None,
) -> int:
    """Export one full image per annotated panel, highlighting that panel only.

    If dirty_indices is provided, only re-exports panels whose shp_index is in
    the set (skips unchanged panels).

    Output: annotated_images/<stem>_<rack>_<panel>_<anomaly>.jpg
    Returns number of files written.
    """
    from PIL import Image, ImageDraw

    out_dir = project.output_geojson.parent / "annotated_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group annotations by image filename — only include dirty panels
    by_image: dict[str, list] = {}
    for rec in project.annotations.values():
        if rec.image_name:
            if dirty_indices is None or rec.shp_index in dirty_indices:
                by_image.setdefault(rec.image_name, []).append(rec)

    # Build set of filenames that SHOULD exist (all annotations, not just dirty)
    valid_names: set[str] = set()
    for rec in project.annotations.values():
        if rec.pixel_coords:
            valid_names.add(exported_image_name(rec))

    exported = 0
    for image_name, recs in by_image.items():
        stem = Path(image_name).stem
        cached = cache.get(stem)
        if cached is None:
            continue

        pixel_dict, _ = cached

        img_path = project.image_dir / image_name
        if not img_path.exists():
            continue

        try:
            base_img = Image.open(img_path).convert("RGB")
        except Exception:
            continue

        for rec in recs:
            coords = rec.pixel_coords if rec.pixel_coords else pixel_dict.get(rec.shp_index)
            if not coords:
                continue

            overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for poly_pts in _split_subpolygons(coords):
                min_x = min(pt[0] for pt in poly_pts)
                min_y = min(pt[1] for pt in poly_pts)
                max_x = max(pt[0] for pt in poly_pts)
                max_y = max(pt[1] for pt in poly_pts)
                draw.rectangle(
                    [min_x, min_y, max_x, max_y],
                    fill=None,
                    outline=(255, 255, 255, 255),
                    width=_LINE_WIDTH,
                )

            composited = Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")
            composited.save(out_dir / exported_image_name(rec))
            exported += 1

    _cleanup_orphaned_images(out_dir, valid_names)
    return exported
