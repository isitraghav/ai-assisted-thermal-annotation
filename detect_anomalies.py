# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=10.0", "geopandas>=0.14", "shapely>=2.0", "rasterio>=1.3", "numpy>=1.26", "tqdm>=4.0", "ultralytics", "torch", "piexif"]
# ///
import argparse
import os
import io
from pathlib import Path
from collections import defaultdict

import geopandas as gpd
import numpy as np
from PIL import Image
from tqdm import tqdm
import rasterio

from ultralytics import YOLO

# Import local utilities
from extractor import (
    load_metashape_model, DemSampler, make_metashape_projector, _camera_position_lla,
    _compute_footprint_bbox, _centroid_in_mask, DEM_MEAN_FALLBACK, IMG_W, IMG_H
)

try:
    from dji_thermal import get_thermal_array
except ImportError as e:
    print("Failed to import dji_thermal. Make sure LD_LIBRARY_PATH is set.")
    raise e

def process_images_and_infer(args):
    folder = Path(args.folder)
    
    # Auto-detect required files
    shp_path = next(folder.glob("*.shp"), None)
    dem_path = next(folder.glob("*.tif"), None)
    xml_path = folder / "cameras.xml"
    
    images_dir = folder / "Image"
    if not images_dir.exists() or not list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.JPG")):
        images_dir = folder # fallback if images are directly in the folder
        
    if not shp_path:
        raise FileNotFoundError(f"Could not find any .shp file in {folder}")
    if not dem_path:
        raise FileNotFoundError(f"Could not find any .tif DEM file in {folder}")
    if not xml_path.exists():
        raise FileNotFoundError(f"Could not find cameras.xml in {folder}")
        
    out_geojson = folder / "detected_anomalies.geojson"
    
    print("Loading YOLO model...")
    model_yolo = YOLO(args.model_path)
    
    print(f"Loading Geometries from {shp_path}...")
    gdf_all = gpd.read_file(shp_path)
    if gdf_all.crs is None:
        gdf_all.set_crs(epsg=4326, inplace=True)
    elif gdf_all.crs.to_epsg() != 4326:
        gdf_all = gdf_all.to_crs(epsg=4326)
        
    sindex = gdf_all.sindex
    geoms = gdf_all.geometry.values
    
    print(f"Loading DEM from {dem_path}...")
    with rasterio.open(dem_path) as ds:
        dem = DemSampler(ds.read(1), ds.transform, ds.nodata, DEM_MEAN_FALLBACK, 0.0)
        
    print(f"Loading Cameras from {xml_path}...")
    model = load_metashape_model(xml_path)
    
    img_paths = list(images_dir.glob("*.JPG")) + list(images_dir.glob("*.jpg"))
    if args.max_images:
        img_paths = img_paths[:args.max_images]
        
    print(f"Processing {len(img_paths)} images for inference...")
    
    # Store predictions: module_idx -> list of (predicted_class, confidence)
    module_predictions = defaultdict(list)
    
    MIN_T, MAX_T = 15.0, 80.0 # Same quantization as extract_dataset.py

    for img_path in tqdm(img_paths):
        pose = model.cameras.get(img_path.stem) if model else None
        if not pose: continue
        
        intr = model.sensors.get(pose.sensor_id)
        if not intr: continue
        
        projector = make_metashape_projector(pose, intr, model)
        cam_lat, cam_lon, cam_alt = _camera_position_lla(pose, model)
        dem_for_image = DemSampler(dem.array, dem.transform, dem.nodata, dem.mean_fallback, 0.0)
                
        footprint = _compute_footprint_bbox(projector, cam_lat, cam_lon, cam_alt, dem_for_image)
        candidate_idx = sindex.query(footprint, predicate="intersects")
        if len(candidate_idx) == 0: continue
        
        # Load absolute thermal float matrix
        try:
            thermal_arr = get_thermal_array(str(img_path))
        except Exception as e:
            # Skip if error loading this thermal image
            continue
            
        # Convert to model-ready grayscale format matching training stats
        norm_arr = np.clip((thermal_arr - MIN_T) / (MAX_T - MIN_T) * 255.0, 0, 255).astype(np.uint8)
        img = Image.fromarray(norm_arr, mode="L")
        
        for idx in candidate_idx:
            geom = geoms[idx]
            if not _centroid_in_mask(geom, projector, dem_for_image): continue
                
            pts = list(geom.exterior.coords)
            lons = np.array([p[0] for p in pts], dtype=np.float64)
            lats = np.array([p[1] for p in pts], dtype=np.float64)
            hs = dem_for_image(lons, lats)
            u, v, front = projector(lons, lats, hs)
            
            if not front.any(): continue
                
            xmin, ymin = max(0, int(u.min()) - 10), max(0, int(v.min()) - 10)
            xmax, ymax = min(IMG_W, int(u.max()) + 10), min(IMG_H, int(v.max()) + 10)
            
            if xmax - xmin < 12 or ymax - ymin < 12: continue
            
            # Make bounding box square to avoid distortion
            side = max(xmax - xmin, ymax - ymin)
            cx, cy = (xmin + xmax) // 2, (ymin + ymax) // 2
            xmin, xmax = cx - side // 2, cx - side // 2 + side
            ymin, ymax = cy - side // 2, cy - side // 2 + side
                
            # Crop the panel from the normalized thermal image
            crop = img.crop((xmin, ymin, xmax, ymax))
            
            # Mask out background bleeding from adjacent panels (dim context)
            from PIL import ImageDraw
            mask = Image.new("L", crop.size, 0)
            draw = ImageDraw.Draw(mask)
            poly_coords = [(px - xmin, py - ymin) for px, py in zip(u, v)]
            draw.polygon(poly_coords, outline=255, fill=255)
            # Dim the background to 30% intensity
            bg = crop.point(lambda p: int(p * 0.3))
            crop = Image.composite(crop, bg, mask)
            
            # Predict using YOLO (we pass the PIL image natively)
            # convert back to RGB just in case YOLO expects 3 channels even internally, or let YOLO handle it
            results = model_yolo.predict(crop, verbose=False)
            
            if len(results) > 0:
                top1_idx = results[0].probs.top1
                top1_conf = results[0].probs.top1conf.item()
                top1_class = results[0].names[top1_idx]
                
                module_predictions[idx].append({
                    "class": top1_class, 
                    "conf": top1_conf, 
                    "image": img_path.name
                })

    print("Aggregating predictions and generating GeoJSON...")
    anomalies = []
    
    import datetime
    for idx, preds in module_predictions.items():
        # Aggregation logic: If any view sees an anomaly, flag it. 
        # Pick the anomaly prediction with the highest confidence.
        non_normal_preds = [p for p in preds if p["class"].lower() != "normal"]
        
        if non_normal_preds:
            # Sort by confidence descending
            best_pred = sorted(non_normal_preds, key=lambda x: x["conf"], reverse=True)[0]
            final_class, final_conf, best_img = best_pred["class"], best_pred["conf"], best_pred["image"]
            
            # Extract all properties from the original shapefile row
            row_props = gdf_all.iloc[idx].drop("geometry").to_dict() if "geometry" in gdf_all.columns else gdf_all.iloc[idx].to_dict()
            
            cx, cy = geoms[idx].centroid.x, geoms[idx].centroid.y
            now = datetime.datetime.now()
            
            anomaly_data = {
                "geometry": geoms[idx],
                "module_id": int(idx),
                "Anomaly": final_class,
                "Longitude": str(round(cx, 15)),
                "Latitude": str(round(cy, 15)),
                "Date": now.strftime("%d/%m/%Y"),
                "Time": now.strftime("%I:%M:%S %p"),
                "Image name": best_img,
                "Hotspot": "2.1",
                "Block": "",
                "ID": "",
                "Make": "",
                "Watt": "",
                "name": str(idx),
                "predicted_anomaly": final_class,
                "confidence": round(final_conf, 4),
                "views_evaluated": len(preds)
            }
            # Merge shapefile properties (anomaly_data will override if there are key conflicts)
            # However we want these specific keys even if they are empty
            for k in anomaly_data.copy():
                if k in row_props and row_props[k] and str(row_props[k]).strip():
                    anomaly_data[k] = row_props[k]
                    del row_props[k]
            
            anomaly_data = {**row_props, **anomaly_data}
            anomalies.append(anomaly_data)

    if not anomalies:
        print("No anomalies detected!")
        return
        
    out_gdf = gpd.GeoDataFrame(anomalies, crs="EPSG:4326")
    out_gdf.to_file(out_geojson, driver="GeoJSON")
    print(f"Successfully saved {len(anomalies)} detected anomalies to {out_geojson} ✅")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DJI M3T Thermal Anomaly Detection CLI using YOLO")
    parser.add_argument("folder", type=str, help="Input folder containing .shp, .tif, cameras.xml, and images (or Image/ subfolder)")
    parser.add_argument("-m", "--model-path", type=str, required=True, help="Path to trained YOLO .pt weights")
    parser.add_argument("--max-images", type=int, default=None, help="Limit number of images to process (useful for testing)")
    
    args = parser.parse_args()
    process_images_and_infer(args)
