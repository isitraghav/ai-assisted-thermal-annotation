# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Pillow>=10.0",
#   "geopandas>=0.14",
#   "shapely>=2.0",
#   "rasterio>=1.3",
#   "numpy>=1.26",
#   "piexif>=1.1",
#   "tqdm>=4.0",
# ]
# ///
"""
extractor.py — Overlay shapefile polygons onto DJI M3T thermal images and
extract annotated images to an output folder.

Projects ``partial.shp`` polygons onto each thermal JPEG using the Metashape
photogrammetry solution in ``cameras.xml`` (full bundle-adjusted pose + Brown-
Conrady calibration).

Middle-60% masking: drone thermal cameras have significant barrel distortion
and geometric inaccuracy in the corners.  Only polygons whose centroid projects
into the central 60% of the image (x ∈ [128,512), y ∈ [102,410) for 640×512)
are drawn and used as an extraction criterion.  Images with no such polygons
are skipped entirely.

All EXIF, XMP, and DJI proprietary APP segments (thermal data) are preserved in
output files via a binary splice strategy.

Usage:
    uv run extractor.py
    uv run extractor.py --image-dir Image --shapefile partial.shp \\
                        --dem DEM.tif --output output --workers 8
    uv run extractor.py --max-images 5          # quick test
    uv run extractor.py --labels                # draw Rack/Panel text on panels
"""

from __future__ import annotations

import argparse
import io
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from math import cos, radians, sin
from pathlib import Path

import geopandas as gpd
import numpy as np
import piexif
import rasterio
import shapely
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRONE_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "M3T": (640, 512),
    "M4T": (1280, 1024),
}

IMG_W, IMG_H = 640, 512  # default M3T; overridden by --drone CLI arg

# Middle 60% region in pixel coordinates (recomputed after CLI arg parsing)
MASK_X0 = int(0.2 * IMG_W)   # 128
MASK_X1 = int(0.8 * IMG_W)   # 512
MASK_Y0 = int(0.2 * IMG_H)   # 102
MASK_Y1 = int(0.8 * IMG_H)   # 410

# Pre-built mask box in pixel space — module-level, thread-safe (read-only)
_MASK_BOX_PX = shapely.box(MASK_X0, MASK_Y0, MASK_X1, MASK_Y1)

DEM_MEAN_FALLBACK = 294.88   # metres — from DEM.tif mean elevation

# WGS84 ellipsoid
WGS84_A  = 6378137.0
WGS84_F  = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

# Overlay appearance
FILL_COLOR = (0, 255, 0, 40)
LINE_COLOR = (0, 255, 0, 255)
DENSIFY    = 8      # ring interpolation factor
JPEG_QUALITY = 95


# ---------------------------------------------------------------------------
# JPEG metadata-preservation helpers
# ---------------------------------------------------------------------------

def find_dqt_offset(data: bytes) -> int:
    """Return byte offset of the first DQT (0xFFDB) marker in a JPEG bytestring."""
    pos = 2  # skip SOI
    while pos + 4 <= len(data):
        marker = struct.unpack_from(">H", data, pos)[0]
        if marker == 0xFFDB:
            return pos
        if (marker & 0xFF00) != 0xFF00:
            break
        length = struct.unpack_from(">H", data, pos + 2)[0]
        pos += 2 + length
    raise ValueError("DQT marker (0xFFDB) not found in JPEG data")


def splice_metadata(original_raw: bytes, new_pixel_raw: bytes) -> bytes:
    """Rebuild JPEG = SOI | original APP segments | new DQT/DHT/SOF/SOS/EOI."""
    orig_dqt = find_dqt_offset(original_raw)
    new_dqt  = find_dqt_offset(new_pixel_raw)
    return b"\xff\xd8" + original_raw[2:orig_dqt] + new_pixel_raw[new_dqt:]


# ---------------------------------------------------------------------------
# GPS / XMP helpers (fallback path when a camera isn't in cameras.xml)
# ---------------------------------------------------------------------------

def _rational_to_float(rational) -> float:
    num, den = rational
    return num / den if den else 0.0


def decode_gps(gps_ifd: dict) -> tuple[float, float, float]:
    """Return (lat_decimal, lon_decimal, alt_m_asl) from a piexif GPS IFD."""
    lat_dms = gps_ifd[piexif.GPSIFD.GPSLatitude]
    lat_ref = gps_ifd[piexif.GPSIFD.GPSLatitudeRef].decode()
    lon_dms = gps_ifd[piexif.GPSIFD.GPSLongitude]
    lon_ref = gps_ifd[piexif.GPSIFD.GPSLongitudeRef].decode()
    alt_r   = gps_ifd.get(piexif.GPSIFD.GPSAltitude, (0, 1))

    lat = (_rational_to_float(lat_dms[0])
           + _rational_to_float(lat_dms[1]) / 60
           + _rational_to_float(lat_dms[2]) / 3600)
    lon = (_rational_to_float(lon_dms[0])
           + _rational_to_float(lon_dms[1]) / 60
           + _rational_to_float(lon_dms[2]) / 3600)
    if lat_ref == "S":
        lat = -lat
    if lon_ref == "W":
        lon = -lon
    alt = _rational_to_float(alt_r)
    return lat, lon, alt


_XMP_YAW     = re.compile(r'GimbalYawDegree="([+-]?\d+\.?\d*)"')
_XMP_REL_ALT = re.compile(r'RelativeAltitude="([+-]?\d+\.?\d*)"')


def _scan_xmp(raw: bytes) -> str | None:
    """Return decoded XMP segment text, or None."""
    pos = 2
    while pos + 4 <= len(raw):
        marker = struct.unpack_from(">H", raw, pos)[0]
        if (marker & 0xFF00) != 0xFF00:
            break
        length = struct.unpack_from(">H", raw, pos + 2)[0]
        seg = raw[pos + 4: pos + 2 + length]
        if b"http" in seg[:100]:
            return seg.decode("latin-1", errors="replace")
        pos += 2 + length
    return None


# ---------------------------------------------------------------------------
# WGS84 ↔ ECEF  (vectorised, numpy)
# ---------------------------------------------------------------------------

def lla_to_ecef(lat_deg, lon_deg, alt_m) -> np.ndarray:
    """Convert WGS84 geographic → ECEF (X, Y, Z) metres.

    Inputs can be scalars or 1-D numpy arrays of the same length.
    Returns an array of shape (..., 3).
    """
    lat = np.deg2rad(np.asarray(lat_deg, dtype=np.float64))
    lon = np.deg2rad(np.asarray(lon_deg, dtype=np.float64))
    alt = np.asarray(alt_m, dtype=np.float64)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + alt) * cos_lat * cos_lon
    y = (n + alt) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + alt) * sin_lat
    return np.stack([x, y, z], axis=-1)


def ecef_to_lla(xyz) -> tuple[float, float, float]:
    """Convert ECEF (metres) → (lat_deg, lon_deg, alt_m). Scalar only."""
    x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
    b    = WGS84_A * (1.0 - WGS84_F)
    ep2  = (WGS84_A * WGS84_A - b * b) / (b * b)
    p    = (x * x + y * y) ** 0.5
    theta = np.arctan2(z * WGS84_A, p * b)
    lat  = np.arctan2(
        z + ep2 * b * np.sin(theta) ** 3,
        p - WGS84_E2 * WGS84_A * np.cos(theta) ** 3,
    )
    lon  = np.arctan2(y, x)
    n    = WGS84_A / np.sqrt(1.0 - WGS84_E2 * np.sin(lat) ** 2)
    alt  = p / np.cos(lat) - n
    return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)


# ---------------------------------------------------------------------------
# Metashape model
# ---------------------------------------------------------------------------

@dataclass
class Intrinsics:
    width: int
    height: int
    f: float
    cx: float
    cy: float
    b1: float
    b2: float
    k1: float
    k2: float
    k3: float
    p1: float
    p2: float


@dataclass
class CameraPose:
    label: str
    sensor_id: int
    R_cl: np.ndarray   # 3×3, camera axes in chunk-local frame
    t_cl: np.ndarray   # 3,   camera origin in chunk-local frame


@dataclass
class MetashapeModel:
    R_chunk: np.ndarray   # 3×3 local → ECEF rotation
    t_chunk: np.ndarray   # 3,  local → ECEF translation (metres, ECEF)
    s_chunk: float        # local → ECEF scale
    sensors: dict[int, Intrinsics]
    cameras: dict[str, CameraPose]   # keyed by label (file stem)


def _float_text(el, default: float = 0.0) -> float:
    if el is None or el.text is None:
        return default
    return float(el.text.strip())


def _intrinsics_from_calibration(cal: ET.Element, sensor_res: tuple[int, int]) -> Intrinsics:
    cal_res = cal.find("resolution")
    if cal_res is not None:
        w = int(cal_res.get("width"))
        h = int(cal_res.get("height"))
    else:
        w, h = sensor_res
    return Intrinsics(
        width=w, height=h,
        f=_float_text(cal.find("f")),
        cx=_float_text(cal.find("cx")),
        cy=_float_text(cal.find("cy")),
        b1=_float_text(cal.find("b1"), 0.0),
        b2=_float_text(cal.find("b2"), 0.0),
        k1=_float_text(cal.find("k1"), 0.0),
        k2=_float_text(cal.find("k2"), 0.0),
        k3=_float_text(cal.find("k3"), 0.0),
        p1=_float_text(cal.find("p1"), 0.0),
        p2=_float_text(cal.find("p2"), 0.0),
    )


def load_metashape_model(cameras_xml: Path) -> MetashapeModel | None:
    """Parse Agisoft Metashape cameras.xml and return a MetashapeModel.

    Returns None if the file is missing or malformed.
    """
    if not cameras_xml.exists():
        return None
    try:
        root = ET.parse(cameras_xml).getroot()
        ct = root.find("chunk/transform")
        if ct is None:
            return None
        R_chunk = np.array(
            list(map(float, ct.find("rotation").text.split())), dtype=np.float64
        ).reshape(3, 3)
        t_chunk = np.array(
            list(map(float, ct.find("translation").text.split())), dtype=np.float64
        )
        s_chunk = float(ct.find("scale").text.strip())

        sensors: dict[int, Intrinsics] = {}
        for sensor in root.findall("chunk/sensors/sensor"):
            sid = int(sensor.get("id"))
            res = sensor.find("resolution")
            sensor_res = (int(res.get("width")), int(res.get("height")))
            cal = sensor.find("calibration")
            if cal is None:
                continue
            sensors[sid] = _intrinsics_from_calibration(cal, sensor_res)

        cameras: dict[str, CameraPose] = {}
        for cam in root.findall("chunk/cameras/camera"):
            t_elem = cam.find("transform")
            if t_elem is None:
                continue  # unaligned
            T = np.array(
                list(map(float, t_elem.text.split())), dtype=np.float64
            ).reshape(4, 4)
            label  = cam.get("label", "")
            sid    = int(cam.get("sensor_id", "0"))
            cameras[label] = CameraPose(
                label=label,
                sensor_id=sid,
                R_cl=T[:3, :3].copy(),
                t_cl=T[:3, 3].copy(),
            )
        return MetashapeModel(
            R_chunk=R_chunk,
            t_chunk=t_chunk,
            s_chunk=s_chunk,
            sensors=sensors,
            cameras=cameras,
        )
    except Exception as exc:
        print(f"WARN  failed to parse {cameras_xml}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Projection closures
# ---------------------------------------------------------------------------

def make_metashape_projector(pose: CameraPose, intr: Intrinsics, model: MetashapeModel):
    """Return a closure that projects (lon, lat, h) arrays → (u, v, front_mask).

    Full Brown-Conrady + affinity/skew (b1, b2) calibration as exported by
    Metashape (note: Metashape swaps p1/p2 vs. OpenCV convention).

    Math:
        P_ecef   = lla_to_ecef(lat, lon, h)
        P_local  = (P_ecef - t_chunk) @ R_chunk / s_chunk
        P_cam    = (P_local - t_cl)    @ R_cl
        xn = X/Z,  yn = Y/Z
        r2 = xn^2 + yn^2
        radial = 1 + k1*r2 + k2*r4 + k3*r6
        xd = xn*radial + p1*(r2+2*xn^2) + 2*p2*xn*yn
        yd = yn*radial + p2*(r2+2*yn^2) + 2*p1*xn*yn
        u  = W/2 + cx + xd*(f + b1) + yd*b2
        v  = H/2 + cy + yd*f
    """
    R_chunk = model.R_chunk
    t_chunk = model.t_chunk
    s_chunk = model.s_chunk
    R_cl    = pose.R_cl
    t_cl    = pose.t_cl
    f, cx, cy = intr.f, intr.cx, intr.cy
    b1, b2    = intr.b1, intr.b2
    k1, k2, k3 = intr.k1, intr.k2, intr.k3
    p1, p2    = intr.p1, intr.p2
    W, H      = intr.width, intr.height
    W2, H2    = W * 0.5, H * 0.5

    def project(lon, lat, h):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        h   = np.asarray(h,   dtype=np.float64)
        p_ecef  = lla_to_ecef(lat, lon, h)                     # (..., 3)
        p_local = (p_ecef - t_chunk) @ R_chunk / s_chunk       # (..., 3)
        p_cam   = (p_local - t_cl) @ R_cl                      # (..., 3)
        zc      = p_cam[..., 2]
        
        # Valid domain check to prevent Brown-Conrady breakdown folding
        # Max theoretical r2 at corners is roughly ~0.06. 
        # Anything > 0.15 is definitively outside the true optical FOV
        # and would cause the polynomial to cross zero and map back to the center.
        front   = (zc > 1e-6)
        
        zc_safe = np.where(front, zc, 1.0)
        xn = p_cam[..., 0] / zc_safe
        yn = p_cam[..., 1] / zc_safe
        r2     = xn * xn + yn * yn
        
        # Mask out points suffering from extreme distortion folding
        front = front & (r2 < 0.15)
        
        radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3))
        xd = xn * radial + p1 * (r2 + 2 * xn * xn) + 2 * p2 * xn * yn
        yd = yn * radial + p2 * (r2 + 2 * yn * yn) + 2 * p1 * xn * yn
        u = W2 + cx + xd * (f + b1) + yd * b2
        v = H2 + cy + yd * f
        return u, v, front

    project.width  = W
    project.height = H
    return project


def make_gps_fallback_projector(
    lat_c: float, lon_c: float, agl_m: float, yaw_rad: float, intr: Intrinsics
):
    """Nadir flat-earth projector using GPS + gimbal yaw.  Uses Metashape
    intrinsics so the lens model is still accurate.
    """
    f, cx, cy = intr.f, intr.cx, intr.cy
    b1, b2    = intr.b1, intr.b2
    k1, k2, k3 = intr.k1, intr.k2, intr.k3
    p1, p2    = intr.p1, intr.p2
    W, H      = intr.width, intr.height
    W2, H2    = W * 0.5, H * 0.5

    lon_m_per_deg = 111320.0 * cos(radians(lat_c))
    lat_m_per_deg = 111320.0
    cy_yaw = cos(yaw_rad)
    sy_yaw = sin(yaw_rad)

    def project(lon, lat, h):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        dx  = (lon - lon_c) * lon_m_per_deg     # metres East
        dy  = (lat - lat_c) * lat_m_per_deg     # metres North
        xc  =  dx * cy_yaw - dy * sy_yaw
        yc  = -dx * sy_yaw - dy * cy_yaw
        zc  = np.full_like(dx, agl_m)
        front = zc > 1e-6
        xn = xc / zc
        yn = yc / zc
        r2     = xn * xn + yn * yn
        
        # Mask out points suffering from extreme distortion folding
        front = front & (r2 < 0.15)
        
        radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3))
        xd = xn * radial + p1 * (r2 + 2 * xn * xn) + 2 * p2 * xn * yn
        yd = yn * radial + p2 * (r2 + 2 * yn * yn) + 2 * p1 * xn * yn
        u = W2 + cx + xd * (f + b1) + yd * b2
        v = H2 + cy + yd * f
        return u, v, front

    project.width  = W
    project.height = H
    return project


# ---------------------------------------------------------------------------
# DEM sampler
# ---------------------------------------------------------------------------

@dataclass
class DemSampler:
    array: np.ndarray
    transform: rasterio.Affine
    nodata: float | None
    mean_fallback: float
    vertical_offset: float = 0.0   # added to every sample (geoid correction)

    def __call__(self, lons, lats):
        """Vectorised nearest-neighbour DEM lookup. Returns elevations in metres."""
        lons = np.asarray(lons, dtype=np.float64)
        lats = np.asarray(lats, dtype=np.float64)
        a, b, c = self.transform.a, self.transform.b, self.transform.c
        d, e, ff = self.transform.d, self.transform.e, self.transform.f
        cols = (lons - c) / a
        rows = (lats - ff) / e
        if b != 0 or d != 0:
            inv  = ~self.transform
            cols = inv.a * lons + inv.b * lats + inv.c
            rows = inv.d * lons + inv.e * lats + inv.f
        cols = np.rint(cols).astype(np.int64)
        rows = np.rint(rows).astype(np.int64)
        h, w = self.array.shape
        in_bounds = (0 <= rows) & (rows < h) & (0 <= cols) & (cols < w)
        out = np.full(lons.shape, self.mean_fallback, dtype=np.float64)
        if in_bounds.any():
            vals = self.array[
                np.where(in_bounds, rows, 0),
                np.where(in_bounds, cols, 0),
            ].astype(np.float64)
            if self.nodata is not None:
                vals = np.where(np.isclose(vals, self.nodata), np.nan, vals)
            vals = np.where(np.isnan(vals), self.mean_fallback, vals)
            out  = np.where(in_bounds, vals, out)
        return out + self.vertical_offset

    def sample_scalar(self, lon: float, lat: float) -> float:
        return float(self(np.array([lon]), np.array([lat]))[0])


# ---------------------------------------------------------------------------
# DEM vertical datum calibration
# ---------------------------------------------------------------------------

def calibrate_dem_vertical_offset(
    image_dir: Path, model: MetashapeModel, dem: DemSampler, max_samples: int = 40
) -> float:
    """Estimate the vertical offset between the DEM's datum and the Metashape
    ellipsoid datum.

    Metashape camera positions are WGS84 ellipsoid heights.  Most DEMs
    (SRTM / Copernicus) are orthometric (MSL, EGM96/2008), so directly feeding
    DEM elevations into lla_to_ecef places ground points ~N metres too low,
    where N is the local geoid undulation (~+44 m at this site).

    Estimates N as the median of  (cam_alt_ellipsoid − xmp_rel_alt) − dem_ortho
    over a sample of aligned images with a parseable RelativeAltitude XMP tag.
    """
    candidates = sorted(image_dir.glob("*.JPG")) + sorted(image_dir.glob("*.jpg"))
    if not candidates:
        return 0.0
    step = max(1, len(candidates) // max_samples)
    offsets: list[float] = []
    for p in candidates[::step][:max_samples]:
        pose = model.cameras.get(p.stem)
        if pose is None:
            continue
        try:
            raw = p.read_bytes()
        except Exception:
            continue
        xmp = _scan_xmp(raw)
        if not xmp:
            continue
        m = _XMP_REL_ALT.search(xmp)
        if not m:
            continue
        try:
            rel_alt = float(m.group(1))
        except ValueError:
            continue
        lat_c, lon_c, alt_c = _camera_position_lla(pose, model)
        dem_val = dem.sample_scalar(lon_c, lat_c) - dem.vertical_offset  # raw DEM value
        offsets.append((alt_c - rel_alt) - dem_val)
    if not offsets:
        return 0.0
    return float(np.median(np.array(offsets)))


# ---------------------------------------------------------------------------
# Camera footprint helpers
# ---------------------------------------------------------------------------

def _camera_position_lla(pose: CameraPose, model: MetashapeModel) -> tuple[float, float, float]:
    """Return bundle-adjusted (lat, lon, alt) of a camera."""
    p_ecef = model.R_chunk @ (model.s_chunk * pose.t_cl) + model.t_chunk
    return ecef_to_lla(p_ecef)


def _compute_footprint_bbox(
    projector, cam_lat: float, cam_lon: float, cam_alt: float, dem: DemSampler
) -> shapely.Geometry:
    """Approximate the image's ground footprint bbox in lon/lat.

    Probes a dense lat/lon grid centred on the camera at the sampled terrain
    elevation, projects through the full camera model, and keeps hits inside
    the image frame.
    """
    terrain_h      = dem.sample_scalar(cam_lon, cam_lat)
    W, H           = projector.width, projector.height
    lat_m_per_deg  = 111320.0
    lon_m_per_deg  = 111320.0 * cos(radians(cam_lat))

    radius_m, n = 60.0, 81
    ds     = np.linspace(-radius_m, radius_m, n)
    dd_lon = np.tile(ds / lon_m_per_deg, n)
    dd_lat = np.repeat(ds / lat_m_per_deg, n)
    lons   = cam_lon + dd_lon
    lats   = cam_lat + dd_lat
    hs     = np.full_like(lons, terrain_h)
    u, v, front = projector(lons, lats, hs)
    inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)

    if inside.sum() < 4:
        radius_m, n = 200.0, 121
        ds     = np.linspace(-radius_m, radius_m, n)
        dd_lon = np.tile(ds / lon_m_per_deg, n)
        dd_lat = np.repeat(ds / lat_m_per_deg, n)
        lons   = cam_lon + dd_lon
        lats   = cam_lat + dd_lat
        hs     = np.full_like(lons, terrain_h)
        u, v, front = projector(lons, lats, hs)
        inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)

    if inside.sum() < 4:
        half_m = 60.0
        return shapely.box(
            cam_lon - half_m / lon_m_per_deg, cam_lat - half_m / lat_m_per_deg,
            cam_lon + half_m / lon_m_per_deg, cam_lat + half_m / lat_m_per_deg,
        )

    lon_hit = lons[inside]
    lat_hit = lats[inside]
    grid_spacing_lon = (ds[1] - ds[0]) / lon_m_per_deg
    grid_spacing_lat = (ds[1] - ds[0]) / lat_m_per_deg
    pad_lon = max(grid_spacing_lon, (lon_hit.max() - lon_hit.min()) * 0.1)
    pad_lat = max(grid_spacing_lat, (lat_hit.max() - lat_hit.min()) * 0.1)
    return shapely.box(
        lon_hit.min() - pad_lon, lat_hit.min() - pad_lat,
        lon_hit.max() + pad_lon, lat_hit.max() + pad_lat,
    )


# ---------------------------------------------------------------------------
# Middle-60% mask helpers
# ---------------------------------------------------------------------------

def _centroid_in_mask(geom, projector, dem: DemSampler) -> bool:
    """Return True if the geometry's centroid projects into the middle-60% region."""
    W, H = projector.width, projector.height
    mask_x0, mask_x1 = int(0.2 * W), int(0.8 * W)
    mask_y0, mask_y1 = int(0.2 * H), int(0.8 * H)
    cx, cy_geo = geom.centroid.x, geom.centroid.y
    h = dem.sample_scalar(cx, cy_geo)
    u, v, front = projector(np.array([cx]), np.array([cy_geo]), np.array([h]))
    return bool(
        front[0]
        and mask_x0 <= u[0] < mask_x1
        and mask_y0 <= v[0] < mask_y1
    )


_COORD_CLAMP = max(IMG_W, IMG_H) * 10  # generous pixel-space clamp

# ---------------------------------------------------------------------------
# Per-image processing
# ---------------------------------------------------------------------------

def process_image(
    img_path: Path,
    out_dir: Path,
    dem: DemSampler,
    geoms,
    sindex,
    gdf,
    model: MetashapeModel | None,
    labels: bool = False,
) -> tuple[str, str, int]:
    """Process a single image.

    Returns (filename, path_kind, n_panels_drawn).
    n_panels_drawn == 0 means the image was skipped (no panels in middle 60%).
    """
    raw = img_path.read_bytes()

    projector = None
    path_kind = ""

    # --- Preferred: full Metashape pose --------------------------------------
    pose = model.cameras.get(img_path.stem) if model else None
    if pose is not None:
        intr = model.sensors.get(pose.sensor_id)
        if intr is None:
            pose = None
    if pose is not None and model is not None:
        projector = make_metashape_projector(pose, intr, model)
        cam_lat, cam_lon, cam_alt = _camera_position_lla(pose, model)
        path_kind = "metashape"

        # The Metashape model implicitly scaled the Z axis (drone elevated to ~107m AGL)
        # to mathematically balance the incorrect thermal focal length optimization (f=1687).
        # We must therefore temporarily ignore the DEM vertical offset (which is calibrated
        # to the true GPS altitude) to preserve this internal geometric consistency.
        # Otherwise, the projection maps onto a surface that is much too close, causing 
        # "very big markings".
        dem_for_image = DemSampler(dem.array, dem.transform, dem.nodata, dem.mean_fallback, vertical_offset=0.0)
    else:
        return img_path.name, "skipped_no_metashape_pose", 0

    # --- Footprint for spatial-index pre-filter ------------------------------
    footprint     = _compute_footprint_bbox(projector, cam_lat, cam_lon, cam_alt, dem_for_image)
    candidate_idx = sindex.query(footprint, predicate="intersects")
    hit_geoms     = geoms[candidate_idx]

    # --- Middle-60% extraction gate ------------------------------------------
    # Only continue if at least one polygon centroid falls in the central region.
    mask_hits = [g for g in hit_geoms if _centroid_in_mask(g, projector, dem_for_image)]
    if not mask_hits:
        return img_path.name, path_kind, 0

    # --- Decode image and set up overlay canvas ------------------------------
    img      = Image.open(io.BytesIO(raw))
    img_rgba = img.convert("RGBA")
    overlay  = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw     = ImageDraw.Draw(overlay)
    
    gray = np.array(img.convert("L"), dtype=np.float32)
    H_img, W_img = gray.shape

    def densify_ring_to_px(ring_coords):
        """Densify ring in lon/lat, sample DEM, project to pixel coords.

        Returns list of (u, v) tuples for front-facing vertices only.
        Drops vertices behind the camera rather than skipping the whole polygon
        (mask-box clip in _clip_ring_to_mask handles edge trimming).
        """
        pts = list(ring_coords)
        if len(pts) < 2:
            return None
        lons_list, lats_list = [], []
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            for k in range(DENSIFY):
                t = k / DENSIFY
                lons_list.append(x0 + t * (x1 - x0))
                lats_list.append(y0 + t * (y1 - y0))
        lons_a = np.array(lons_list, dtype=np.float64)
        lats_a = np.array(lats_list, dtype=np.float64)
        hs     = dem_for_image(lons_a, lats_a)
        u, v, front = projector(lons_a, lats_a, hs)
        if not front.any():
            return None
        # If any vertex is behind the camera, skip this polygon entirely.
        # Dropping mid-ring vertices breaks the polygon topology and causes
        # spike artifacts when PIL connects the remaining vertices.
        if not front.all():
            return None
        return list(zip(u.tolist(), v.tolist()))

    n_panels = 0
    if labels:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 9)
        except Exception:
            font = ImageFont.load_default()

    for idx, geom in enumerate(hit_geoms):
        if not _centroid_in_mask(geom, projector, dem_for_image):
            continue
            
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        drew_any = False
        
        for poly in polys:
            px_coords = densify_ring_to_px(poly.exterior.coords)
            if not px_coords or len(px_coords) < 3:
                continue
            
            # --- Snap polygon to darkest image edges (blackish lining) ---
            pts = np.array(px_coords)
            
            # Create a localized bounding box for the polygon search
            x_min, x_max = int(pts[:, 0].min()), int(pts[:, 0].max())
            y_min, y_max = int(pts[:, 1].min()), int(pts[:, 1].max())
            
            SEARCH_RADIUS = 10
            pad = SEARCH_RADIUS + 2
            if x_min - pad >= 0 and x_max + pad < W_img and y_min - pad >= 0 and y_max + pad < H_img:
                # Fast block matrix extraction
                pts_lx = np.round(pts[:, 0] - x_min + pad).astype(int)
                pts_ly = np.round(pts[:, 1] - y_min + pad).astype(int)
                patch = gray[y_min - pad : y_max + pad + 1, x_min - pad : x_max + pad + 1]
                
                # Vectorize the 21x21 search
                dy_vals = np.arange(-SEARCH_RADIUS, SEARCH_RADIUS + 1)
                dx_vals = np.arange(-SEARCH_RADIUS, SEARCH_RADIUS + 1)
                
                # Expand to (N, 21, 21)
                all_y = pts_ly[:, None, None] + dy_vals[:, None]
                all_x = pts_lx[:, None, None] + dx_vals[None, :]
                
                scores = patch[all_y, all_x].mean(axis=0)  # (21, 21) shape
                best_idx = np.unravel_index(np.argmin(scores), scores.shape)
                best_dy = dy_vals[best_idx[0]]
                best_dx = dx_vals[best_idx[1]]
                
                snapped_coords = pts + [best_dx, best_dy]
            else:
                snapped_coords = pts
            
            # Draw as bounding box rectangles rather than exact polygons
            min_x = int(np.min(snapped_coords[:, 0]))
            min_y = int(np.min(snapped_coords[:, 1]))
            max_x = int(np.max(snapped_coords[:, 0]))
            max_y = int(np.max(snapped_coords[:, 1]))
            draw.rectangle([min_x, min_y, max_x, max_y], fill=FILL_COLOR, outline=LINE_COLOR)
            drew_any = True
            
        if drew_any:
            n_panels += 1

            # Optionally label with Rack/Panel ID at centroid
            if labels:
                cx_geo, cy_geo = geom.centroid.x, geom.centroid.y
                h_c = dem_for_image.sample_scalar(cx_geo, cy_geo)
                uc, vc, fc = projector(
                    np.array([cx_geo]), np.array([cy_geo]), np.array([h_c])
                )
                _pw, _ph = projector.width, projector.height
                _mx0, _mx1 = int(0.2 * _pw), int(0.8 * _pw)
                _my0, _my1 = int(0.2 * _ph), int(0.8 * _ph)
                if fc[0] and _mx0 <= uc[0] < _mx1 and _my0 <= vc[0] < _my1:
                    real_idx = candidate_idx[idx] if hasattr(candidate_idx, '__len__') else idx
                    rack  = gdf.iloc[real_idx].get("Rack",   "")
                    panel = gdf.iloc[real_idx].get("Panel",  "")
                    label_text = f"{rack}/{panel}" if rack or panel else ""
                    if label_text:
                        draw.text((uc[0], vc[0]), label_text,
                                  fill=(255, 255, 0, 200), font=font)

    img_rgba  = Image.alpha_composite(img_rgba, overlay)
    img_final = img_rgba.convert("RGB")

    buf = io.BytesIO()
    img_final.save(buf, format="JPEG", quality=JPEG_QUALITY, subsampling=0)
    spliced = splice_metadata(raw, buf.getvalue())

    out_path = out_dir / img_path.name
    out_path.write_bytes(spliced)
    return img_path.name, path_kind, n_panels


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Overlay shapefile polygons on drone thermal images (middle-60% only) "
            "and extract annotated images to an output folder."
        )
    )
    parser.add_argument("--image-dir",   default="Image",
                        help="Directory containing thermal JPEG images (default: Image)")
    parser.add_argument("--shapefile",   default="partial.shp",
                        help="Shapefile with panel polygons (default: partial.shp)")
    parser.add_argument("--dem",         default="DEM.tif",
                        help="Digital elevation model GeoTIFF (default: DEM.tif)")
    parser.add_argument("--cameras-xml", default="cameras.xml",
                        help="Agisoft Metashape cameras.xml (default: cameras.xml)")
    parser.add_argument("--output",      default="output",
                        help="Output directory for annotated images (default: output)")
    parser.add_argument("--workers",     type=int,
                        default=min(8, os.cpu_count() or 4),
                        help="Number of parallel workers (default: min(8, cpu_count))")
    parser.add_argument("--labels",      action="store_true",
                        help="Draw Rack/Panel labels at polygon centroids")
    parser.add_argument("--max-images",  type=int, default=None,
                        help="Process at most N images (useful for quick tests)")
    parser.add_argument("--drone",       choices=["M3T", "M4T"], default="M3T",
                        help="Drone model — sets thermal image resolution (default: M3T)")
    args = parser.parse_args()

    # Update global resolution constants for this run
    global IMG_W, IMG_H, MASK_X0, MASK_X1, MASK_Y0, MASK_Y1, _MASK_BOX_PX, _COORD_CLAMP
    IMG_W, IMG_H = DRONE_RESOLUTIONS[args.drone]
    MASK_X0 = int(0.2 * IMG_W)
    MASK_X1 = int(0.8 * IMG_W)
    MASK_Y0 = int(0.2 * IMG_H)
    MASK_Y1 = int(0.8 * IMG_H)
    _MASK_BOX_PX = shapely.box(MASK_X0, MASK_Y0, MASK_X1, MASK_Y1)
    _COORD_CLAMP = max(IMG_W, IMG_H) * 10

    image_dir = Path(args.image_dir)
    out_dir   = Path(args.output)
    shp_path  = Path(args.shapefile)
    dem_path  = Path(args.dem)

    for p, label in [(image_dir, "image-dir"), (shp_path, "shapefile"), (dem_path, "dem")]:
        if not p.exists():
            sys.exit(f"ERROR: {label} not found: {p}")

    # Load shapefile
    print(f"Loading shapefile: {shp_path}")
    gdf    = gpd.read_file(shp_path)
    geoms  = gdf.geometry.values
    sindex = gdf.sindex
    print(f"  {len(gdf):,} polygons, spatial index built")

    # Load DEM
    print(f"Loading DEM: {dem_path}")
    with rasterio.open(dem_path) as ds:
        dem_array     = ds.read(1)
        dem_transform = ds.transform
        dem_nodata    = ds.nodata
    dem = DemSampler(dem_array, dem_transform, dem_nodata, DEM_MEAN_FALLBACK)
    print(f"  DEM shape: {dem_array.shape}, nodata={dem_nodata}")

    # Load Metashape model
    cameras_xml = Path(args.cameras_xml)
    model = load_metashape_model(cameras_xml)
    if model is not None:
        print(
            f"Loaded Metashape model: {len(model.cameras):,} cameras, "
            f"{len(model.sensors)} sensors, scale={model.s_chunk:.4f}"
        )
        offset = calibrate_dem_vertical_offset(image_dir, model, dem)
        dem.vertical_offset = offset
        print(f"DEM vertical offset (ellipsoid − DEM datum): {offset:+.2f} m")
    else:
        print(f"WARN  {cameras_xml} not found or unreadable — GPS fallback for all images")

    # Enumerate images
    images = sorted(image_dir.glob("*.JPG")) + sorted(image_dir.glob("*.jpg"))
    if not images:
        sys.exit(f"ERROR: No JPEG files found in {image_dir}")
    if args.max_images:
        images = images[: args.max_images]
    print(
        f"Processing {len(images):,} images with {args.workers} workers "
        f"(mask: middle 60% = x∈[{MASK_X0},{MASK_X1}) y∈[{MASK_Y0},{MASK_Y1})) …"
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    counts  = {"metashape": 0, "gps_fallback": 0}
    skipped = 0
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_image, p, out_dir, dem, geoms, sindex, gdf, model, args.labels
            ): p
            for p in images
        }
        with tqdm(total=len(images), unit="img") as pbar:
            for fut in as_completed(futures):
                src = futures[fut]
                try:
                    _, kind, n_panels = fut.result()
                    if n_panels == 0:
                        skipped += 1
                    else:
                        counts[kind] = counts.get(kind, 0) + 1
                except Exception as exc:
                    errors.append((src.name, str(exc)))
                    tqdm.write(f"  WARN  {src.name}: {exc}")
                pbar.update(1)

    written = sum(counts.values())
    total   = len(images)
    print(f"\nDone. {written}/{total} images written to {out_dir}/")
    print(f"  Metashape pose                    : {counts.get('metashape', 0):,}")
    print(f"  GPS fallback                      : {counts.get('gps_fallback', 0):,}")
    print(f"  Skipped (no panels in middle 60%) : {skipped:,}")
    if errors:
        print(f"  Errors                            : {len(errors)}")
        for name, msg in errors:
            print(f"    {name}: {msg}")
    else:
        print(f"  Errors                            : 0")


if __name__ == "__main__":
    main()
