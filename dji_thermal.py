import ctypes
import os
import sys
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the DJI Thermal SDK for the current platform
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent

if sys.platform == "win32":
    _SDK_SUBPATH = "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/windows/release_x64"
    _LIB_NAME    = "libdirp.dll"
else:
    _SDK_SUBPATH = "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/linux/release_x64"
    _LIB_NAME    = "libdirp.so"

SDK_DIR = str(_ROOT / _SDK_SUBPATH)

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


def get_thermal_array(rjpeg_path):
    if libdirp is None:
        raise RuntimeError("DJI Thermal SDK not loaded")

    with open(rjpeg_path, "rb") as f:
        data = f.read()

    ph = DIRP_HANDLE()
    data_buffer = ctypes.create_string_buffer(data)
    ret = libdirp.dirp_create_from_rjpeg(data_buffer, len(data), ctypes.byref(ph))

    if ret != 0:
        raise ValueError(f"Failed to decode RJPEG (error {ret}): {rjpeg_path}")

    # 640x512 resolution for M3T
    img_buf = (ctypes.c_int16 * (640 * 512))()

    ret2 = libdirp.dirp_measure(ph, img_buf, ctypes.sizeof(img_buf))
    if ret2 != 0:
        libdirp.dirp_destroy(ph)
        raise ValueError(f"Failed to measure thermal (error {ret2}): {rjpeg_path}")

    arr = np.ctypeslib.as_array(img_buf).reshape((512, 640)).astype(np.float32)
    arr = arr / 10.0  # Convert to Celsius

    libdirp.dirp_destroy(ph)
    return arr
