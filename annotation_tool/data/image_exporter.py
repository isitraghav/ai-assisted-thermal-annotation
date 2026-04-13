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


def export_annotated_images(project: ProjectState, cache) -> int:
    """Render every image that has annotations and save to annotated_images/.

    Draws all visible polygons (unannotated green, annotated colored) on a
    copy of the original thermal image.  Returns the number of files written.
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
            continue  # projection not yet computed for this image

        pixel_dict, _ = cached

        img_path = project.image_dir / image_name
        if not img_path.exists():
            continue

        try:
            base_img = Image.open(img_path).convert("RGB")
        except Exception:
            continue

        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Annotated polygons only — white border, no fill
        for rec in recs:
            coords = pixel_dict.get(rec.shp_index)
            if not coords:
                continue
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

        composited = Image.alpha_composite(base_img.convert("RGBA"), overlay)
        composited.convert("RGB").save(out_dir / image_name)
        exported += 1

    return exported
