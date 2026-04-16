"""Export thermal images with polygon overlays to annotated_images/."""

from __future__ import annotations

from pathlib import Path

from annotation_tool.data.project import ProjectState

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


def _unique_path(out_dir: Path, name: str) -> Path:
    """Return a path that doesn't collide with existing files."""
    p = out_dir / name
    if not p.exists():
        return p
    stem, ext = name.rsplit(".", 1) if "." in name else (name, "jpg")
    counter = 1
    while p.exists():
        p = out_dir / f"{stem}_{counter}.{ext}"
        counter += 1
    return p


def _rec_label(rec) -> str:
    """Build a filename label from annotation values, e.g. R1_P3_Cell."""
    parts = [rec.rack, rec.panel, rec.anomaly.replace(" ", "_")]
    return "_".join(p for p in parts if p)


def export_annotated_images(project: ProjectState, cache) -> int:
    """Export one full image per annotated panel, highlighting that panel only.

    Output: annotated_images/<stem>_<rack>_<panel>_<anomaly>.jpg
    Returns number of files written.
    """
    from PIL import Image, ImageDraw

    out_dir = project.output_geojson.parent / "annotated_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group annotations by image filename
    by_image: dict[str, list] = {}
    for rec in project.annotations.values():
        if rec.image_name:
            by_image.setdefault(rec.image_name, []).append(rec)

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
            coords = pixel_dict.get(rec.shp_index)
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
            label = _rec_label(rec)
            composited.save(_unique_path(out_dir, f"{stem}_{label}.jpg"))
            exported += 1

    return exported
