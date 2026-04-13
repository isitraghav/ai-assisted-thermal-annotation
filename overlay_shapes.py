# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=10.0", "geopandas>=0.14", "shapely>=2.0", "rasterio>=1.3", "numpy>=1.26", "tqdm>=4.0", "piexif>=1.1"]
# ///
import argparse
import sys
from pathlib import Path
import subprocess

def main():
    parser = argparse.ArgumentParser(description="DJI M3T Thermal Shapefile Overlay CLI")
    parser.add_argument("folder", type=str, help="Input folder containing .shp, .tif, cameras.xml, and images (or Image/ subfolder)")
    parser.add_argument("--max-images", type=int, default=None, help="Limit number of images to output")
    
    args = parser.parse_args()
    folder = Path(args.folder)
    
    # Auto-detect required files
    shp_path = next(folder.glob("*.shp"), None)
    dem_path = next(folder.glob("*.tif"), None)
    xml_path = folder / "cameras.xml"
    
    images_dir = folder / "Image"
    if not images_dir.exists() or not (list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.JPG"))):
        images_dir = folder # fallback if images are directly in the folder
        
    if not shp_path:
        raise FileNotFoundError(f"Could not find any .shp file in {folder}")
    if not dem_path:
        raise FileNotFoundError(f"Could not find any .tif DEM file in {folder}")
    if not xml_path.exists():
        raise FileNotFoundError(f"Could not find cameras.xml in {folder}")
        
    output_dir = folder / "output_overlays"
    output_dir.mkdir(exist_ok=True, parents=True)
    
    cmd = [
        sys.executable, "extractor.py",
        "--image-dir", str(images_dir),
        "--shapefile", str(shp_path),
        "--dem", str(dem_path),
        "--cameras-xml", str(xml_path),
        "--output", str(output_dir)
    ]
    if args.max_images:
        cmd.extend(["--max-images", str(args.max_images)])
        
    print(f"Running overlay with detected paths from '{folder}'...")
    subprocess.run(cmd, check=True)
    print(f"Done! Overlaid images are saved in: {output_dir}")

if __name__ == "__main__":
    main()
