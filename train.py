# /// script
# dependencies = ["ultralytics"]
# ///
"""
Train YOLO11 segmentation on all training_dataset/ folders found under a root folder.

Usage:
    uv run train.py <root_folder> [options]

    uv run train.py /path/to/sessions
    uv run train.py /path/to/sessions --model yolo11s-seg.pt --epochs 150 --batch 8
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

CLASSES = [
    "bypass_diode", "cell", "dust", "module_missing", "module_offline",
    "multi_cell", "partial_string_offline", "physical_damage", "shading",
    "short_circuit", "string_offline", "vegetation",
]


def find_datasets(root: Path) -> list[Path]:
    """Find all training_dataset/ dirs with images+labels under root.
    Also handles root itself being a training_dataset/."""
    candidates = []
    # Root itself might be a training_dataset
    if (root / "images" / "train").exists() and (root / "labels" / "train").exists():
        candidates.append(root)
    # Recurse for nested ones
    for d in sorted(root.rglob("training_dataset")):
        if d == root:
            continue
        if d.is_dir() and (d / "images" / "train").exists() and (d / "labels" / "train").exists():
            candidates.append(d)
    return candidates


def merge(datasets: list[Path], merged_dir: Path) -> None:
    """Symlink all images+labels into merged_dir, prefixing with ds000_ to avoid name collisions."""
    img_out = merged_dir / "images" / "train"
    lbl_out = merged_dir / "labels" / "train"
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    total_img = total_lbl = 0
    for i, ds in enumerate(datasets):
        prefix = f"ds{i:03d}_"
        for img in sorted((ds / "images" / "train").glob("*")):
            dst = img_out / (prefix + img.name)
            if not dst.exists():
                dst.symlink_to(img.resolve())
            total_img += 1
        for lbl in sorted((ds / "labels" / "train").glob("*.txt")):
            dst = lbl_out / (prefix + lbl.stem + ".txt")
            # label stem must match image stem — keep consistent with prefix
            if not dst.exists():
                dst.symlink_to(lbl.resolve())
            total_lbl += 1

    print(f"  {total_img} images, {total_lbl} label files from {len(datasets)} dataset(s)")


def write_yaml(merged_dir: Path) -> Path:
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASSES))
    yaml_path = merged_dir / "dataset.yaml"
    yaml_path.write_text(
        f"path: {merged_dir.resolve()}\n"
        f"train: images/train\n"
        f"val: images/train\n"
        f"names:\n{names}\n"
    )
    return yaml_path


def main():
    p = argparse.ArgumentParser(
        description="Train YOLO segmentation on all annotation sessions in a folder."
    )
    p.add_argument("root", type=Path,
                   help="Folder containing session output dirs (each with training_dataset/ inside)")
    p.add_argument("--model",  default="yolo11n-seg.pt",
                   help="YOLO model weights to start from (default: yolo11n-seg.pt)")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz",  type=int, default=640)
    p.add_argument("--batch",  type=int, default=16)
    p.add_argument("--name",   default="thermal_anomaly_seg",
                   help="Run name (saved under runs/segment/)")
    p.add_argument("--keep-merged", action="store_true",
                   help="Keep merged_dataset/ folder after training")
    args = p.parse_args()

    root = args.root.resolve()
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {root} ...")
    datasets = find_datasets(root)
    if not datasets:
        print("No training_dataset/ folders found. Run the annotation tool first.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(datasets)} dataset(s):")
    for ds in datasets:
        n_img = len(list((ds / "images" / "train").glob("*")))
        n_lbl_nonempty = sum(
            1 for f in (ds / "labels" / "train").glob("*.txt") if f.stat().st_size > 0
        )
        print(f"  {ds.relative_to(root.parent)}  ({n_img} images, {n_lbl_nonempty} annotated)")

    merged_dir = root / "_merged_dataset"
    if merged_dir.exists():
        shutil.rmtree(merged_dir)

    print(f"\nMerging → {merged_dir}")
    merge(datasets, merged_dir)
    yaml_path = write_yaml(merged_dir)

    annotated_count = sum(
        1 for f in (merged_dir / "labels" / "train").glob("*.txt")
        if f.stat().st_size > 0
    )
    print(f"  {annotated_count} images with polygon labels\n")

    if annotated_count == 0:
        print("Warning: no annotated images — model will be useless.", file=sys.stderr)

    print(f"Model   : {args.model}")
    print(f"Epochs  : {args.epochs}")
    print(f"Imgsz   : {args.imgsz}")
    print(f"Batch   : {args.batch}")
    print(f"Run name: {args.name}\n")

    from ultralytics import YOLO
    model = YOLO(args.model)
    model.train(
        data=str(yaml_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        name=args.name,
        task="segment",
    )

    if not args.keep_merged:
        shutil.rmtree(merged_dir)

    print("\nDone.")
    print("Weights → runs/segment/" + args.name + "/weights/best.pt")


if __name__ == "__main__":
    main()
