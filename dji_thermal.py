import ctypes
import os
import sys
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the DJI Thermal SDK for the current platform
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent

if getattr(sys, "frozen", False):
    # PyInstaller bundle — DLLs/SOs are packed into dji_sdk_libs/ next to the exe
    _ROOT        = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    _SDK_SUBPATH = "dji_sdk_libs"
elif sys.platform == "win32":
    _SDK_SUBPATH = "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/windows/release_x64"
else:
    _SDK_SUBPATH = "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/linux/release_x64"

_LIB_NAME = "libdirp.dll" if sys.platform == "win32" else "libdirp.so"
SDK_DIR   = str(_ROOT / _SDK_SUBPATH)

# On Windows, register the SDK dir so DLL dependencies resolve automatically
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(SDK_DIR)
    except OSError:
        pass

# On Linux/macOS, warn if LD_LIBRARY_PATH is not set
if sys.platform != "win32":
    if SDK_DIR not in os.environ.get("LD_LIBRARY_PATH", ""):
        print(f"Warning: LD_LIBRARY_PATH must include {SDK_DIR} before importing this module")

try:
    libdirp = ctypes.cdll.LoadLibrary(os.path.join(SDK_DIR, _LIB_NAME))
except Exception as e:
    print(f"Failed to load DJI Thermal SDK: {e}")
    libdirp = None

DIRP_HANDLE = ctypes.c_void_p

DRONE_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "M3T": (640, 512),
    "M4T": (1280, 1024),
}


class _DirpResolution(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int)]


def get_thermal_array(rjpeg_path, drone_model: str = "M3T"):
    if libdirp is None:
        raise RuntimeError("DJI Thermal SDK not loaded")

    with open(rjpeg_path, "rb") as f:
        data = f.read()

    ph = DIRP_HANDLE()
    data_buffer = ctypes.create_string_buffer(data)
    ret = libdirp.dirp_create_from_rjpeg(data_buffer, len(data), ctypes.byref(ph))

    if ret != 0:
        raise ValueError(f"Failed to decode RJPEG (error {ret}): {rjpeg_path}")

    # Query actual resolution from SDK — avoids SIZE_NOT_MATCH (-8) on unexpected sensors
    res = _DirpResolution()
    ret_res = libdirp.dirp_get_rjpeg_resolution(ph, ctypes.byref(res))
    if ret_res == 0 and res.width > 0 and res.height > 0:
        w, h = res.width, res.height
    else:
        # Fallback to known drone resolution
        w, h = DRONE_RESOLUTIONS.get(drone_model, (640, 512))

    img_buf = (ctypes.c_int16 * (w * h))()

    ret2 = libdirp.dirp_measure(ph, img_buf, ctypes.sizeof(img_buf))
    if ret2 != 0:
        libdirp.dirp_destroy(ph)
        raise ValueError(f"Failed to measure thermal (error {ret2}): {rjpeg_path}")

    arr = np.ctypeslib.as_array(img_buf).reshape((h, w)).astype(np.float32)
    arr = arr / 10.0  # Convert to Celsius

    libdirp.dirp_destroy(ph)
    return arr
