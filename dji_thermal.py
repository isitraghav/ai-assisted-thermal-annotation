import ctypes
import os
import numpy as np

# Load DJI Thermal SDK
SDK_DIR = os.path.abspath("dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/linux/release_x64")
if "LD_LIBRARY_PATH" not in os.environ or SDK_DIR not in os.environ["LD_LIBRARY_PATH"]:
    print(f"Warning: LD_LIBRARY_PATH must include {SDK_DIR} before importing this module")
    
# Try loading, assume LD_LIBRARY_PATH was set via OS or beforehand
try:
    libdirp = ctypes.cdll.LoadLibrary(os.path.join(SDK_DIR, "libdirp.so"))
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
    img_buf = (ctypes.c_int16 * (640*512))()
    
    ret2 = libdirp.dirp_measure(ph, img_buf, ctypes.sizeof(img_buf))
    if ret2 != 0:
        libdirp.dirp_destroy(ph)
        raise ValueError(f"Failed to measure thermal (error {ret2}): {rjpeg_path}")
    
    arr = np.ctypeslib.as_array(img_buf).reshape((512, 640)).astype(np.float32)
    arr = arr / 10.0 # Convert to Celsius
    
    libdirp.dirp_destroy(ph)
    
    return arr
