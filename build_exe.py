# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "PyQt5>=5.15",
#   "geopandas>=0.14",
#   "shapely>=2.0",
#   "rasterio>=1.3",
#   "numpy>=1.26",
#   "Pillow>=10.0",
#   "piexif>=1.1",
#   "tqdm>=4.0",
#   "pyinstaller>=6.0",
# ]
# ///
"""Build the Thermal Annotation Tool executable.

Run with:
    uv run build_exe.py
"""
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--clean", "-y", "annotation_tool.spec"],
    check=True,
)
