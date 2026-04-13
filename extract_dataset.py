# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=10.0", "geopandas>=0.14", "shapely>=2.0", "rasterio>=1.3", "numpy>=1.26", "piexif>=1.1", "tqdm>=4.0"]
# ///
import os, io, json
from pathlib import Path
import geopandas as gpd
import numpy as np
from PIL import Image
from tqdm import tqdm

from extractor import (
    load_metashape_model, DemSampler, make_metashape_projector, _camera_position_lla,
    _compute_footprint_bbox, _centroid_in_mask, splice_metadata, DEM_MEAN_FALLBACK, IMG_W, IMG_H
)

def build_yolo_dataset(images_dir, shp_path, geojson_path, dem_path, xml_path, output_dir, max_images=50):
    os.makedirs(output_dir, exist_ok=True)
    
    print("Loading Geometries & Anomalies...")
    gdf_all = gpd.read_file(shp_path)
    gdf_anom = gpd.read_file(geojson_path)
    
    if gdf_all.crs is None: gdf_all.set_crs(epsg=4326, inplace=True)
    if gdf_anom.crs is None: gdf_anom.set_crs(epsg=4326, inplace=True)
    else: gdf_anom = gdf_anom.to_crs(epsg=4326)
    
    # 1. Spatial Join to label anomalous modules based on the GeoJSON report
    joined = gpd.sjoin(gdf_all, gdf_anom, how="left", predicate="intersects")
    gdf_all["Label"] = "Normal"
    gdf_all["Anomaly_Name"] = ""
    for idx, row in joined.iterrows():
        if isinstance(row.get("Anomaly"), str):
            gdf_all.loc[idx, "Label"] = row["Anomaly"]
        val = row.get("name")
        if isinstance(val, (str, int, float)) and str(val).strip():
            gdf_all.loc[idx, "Anomaly_Name"] = str(val).strip()
            
    print(f"Dataset Split Details: {gdf_all['Label'].value_counts().to_dict()}")
    
    for label in gdf_all["Label"].unique():
        safe_label = str(label).replace("/", "_").replace(" ", "_")
        os.makedirs(Path(output_dir) / safe_label, exist_ok=True)

    geoms, sindex, labels = gdf_all.geometry.values, gdf_all.sindex, gdf_all["Label"].values
    
    def safe_get(col):
        return gdf_all[col].values if col in gdf_all.columns else np.array([""] * len(gdf_all))
    
    racks, panels, modules, anomaly_names = safe_get("Rack"), safe_get("Panel"), safe_get("Module"), safe_get("Anomaly_Name")
    
    import rasterio
    with rasterio.open(dem_path) as ds:
        dem = DemSampler(ds.read(1), ds.transform, ds.nodata, DEM_MEAN_FALLBACK, 0.0)
    
    model = load_metashape_model(Path(xml_path))
    img_paths = list(Path(images_dir).glob("*.JPG")) + list(Path(images_dir).glob("*.jpg"))
    if max_images:
        img_paths = img_paths[:max_images]
    extracted = set() # Avoid extracting the same module multiple times
    
    print(f"Extracting individual panels from {len(img_paths)} drone frames...")
    for img_path in tqdm(img_paths):
        raw = img_path.read_bytes()
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
            
        try:
            from dji_thermal import get_thermal_array
            thermal_arr = get_thermal_array(str(img_path))
            # Map absolute temperatures [15 C, 80 C] into [0, 255] discrete physical arrays
            MIN_T, MAX_T = 15.0, 80.0
            norm_arr = np.clip((thermal_arr - MIN_T) / (MAX_T - MIN_T) * 255.0, 0, 255).astype(np.uint8)
            img = Image.fromarray(norm_arr, mode="L")
        except Exception as e:
            print(f"Failed to load literal thermal array for {img_path}: {e}")
            img = Image.open(io.BytesIO(raw)).convert("L")
        
        for idx in candidate_idx:
            if idx in extracted: continue
            
            geom, label = geoms[idx], labels[idx]
            rack, panel, mod_num, anom_key = racks[idx], panels[idx], modules[idx], anomaly_names[idx]
            
            # Undersample Normal class rigorously so anomalies actually get trained
            # Normal class drops 90% of samples (retains ~10%) to balance the distributions
            if label == "Normal" and np.random.rand() > 0.10:
                continue
                
            if not _centroid_in_mask(geom, projector, dem_for_image): continue
                
            pts = list(geom.exterior.coords)
            lons, lats = np.array([p[0] for p in pts], dtype=np.float64), np.array([p[1] for p in pts], dtype=np.float64)
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
                
            crop = img.crop((xmin, ymin, xmax, ymax))
            
            # Mask out background bleeding from adjacent panels (dim context)
            from PIL import ImageDraw
            mask = Image.new("L", crop.size, 0)
            draw = ImageDraw.Draw(mask)
            poly_coords = [(px - xmin, py - ymin) for px, py in zip(u, v)]
            draw.polygon(poly_coords, outline=255, fill=255)
            # Dim the background to 30% intensity so context is visible but anomaly defaults to the target panel
            bg = crop.point(lambda p: int(p * 0.3))
            crop = Image.composite(crop, bg, mask)
            
            # Binary map the original EXIF and APP4 drone thermal byte segments into the micro cropped panel 
            out_raw = io.BytesIO()
            crop.save(out_raw, format="JPEG", quality=100)
            final_bytes = splice_metadata(raw, out_raw.getvalue())
            
            safe_label = str(label).replace("/", "_").replace(" ", "_")
            
            suffix = []
            if anom_key: suffix.append(f"key{anom_key}".replace(" ", ""))
            if rack: suffix.append(f"R{rack}".replace(" ", ""))
            if panel: suffix.append(f"P{panel}".replace(" ", ""))
            if mod_num: suffix.append(f"M{mod_num}".replace(" ", ""))
            
            suffix_str = "_".join(suffix) if suffix else f"mod{idx}"
            
            out_name = Path(output_dir) / safe_label / f"{img_path.stem}_{suffix_str}.jpg"
            out_name.parent.mkdir(parents=True, exist_ok=True)
            out_name.write_bytes(final_bytes)
            
            extracted.add(idx)

if __name__ == "__main__":
    # We limit images to 200 to keep timeframe manageable right now
    base_folder = "training_data/dataset1"
    build_yolo_dataset(
        os.path.join(base_folder, "Image"), 
        os.path.join(base_folder, "partial.shp"), 
        os.path.join(base_folder, "1775925810686-report.geojson"), 
        os.path.join(base_folder, "DEM.tif"), 
        os.path.join(base_folder, "cameras.xml"), 
        "yolo_dataset", 
        max_images=200
    )
