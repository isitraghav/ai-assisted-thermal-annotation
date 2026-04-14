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
# ]
# ///
"""Thermal Annotation Tool — entry point.

Run with:
    uv run annotation_tool/main.py
    # or from project root:
    python -m annotation_tool  (after activating uv venv)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# -----------------------------------------------------------------------
# 1. Patch sys.path so parent-directory modules (extractor, dji_thermal) are importable
# -----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # Running as a PyInstaller bundle — bundled modules live in sys._MEIPASS
    ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# -----------------------------------------------------------------------
# 2. Set library search path for the DJI Thermal SDK *before* any ctypes load
# -----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    SDK_DIR = str(ROOT / "dji_sdk_libs")
elif sys.platform == "win32":
    SDK_DIR = str(ROOT / "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/windows/release_x64")
else:
    SDK_DIR = str(ROOT / "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/linux/release_x64")

if sys.platform == "win32":
    # Python 3.8+: register DLL directory so ctypes dependency chain resolves
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(SDK_DIR)
        except OSError:
            pass
    existing_path = os.environ.get("PATH", "")
    if SDK_DIR not in existing_path:
        os.environ["PATH"] = SDK_DIR + os.pathsep + existing_path
else:
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if SDK_DIR not in existing_ld:
        os.environ["LD_LIBRARY_PATH"] = SDK_DIR + (":" + existing_ld if existing_ld else "")

# -----------------------------------------------------------------------
# 3. Launch Qt application
# -----------------------------------------------------------------------
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor

from annotation_tool.app_window import AppWindow


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(45, 45, 48))
    p.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    p.setColor(QPalette.Base,            QColor(30, 30, 30))
    p.setColor(QPalette.AlternateBase,   QColor(45, 45, 48))
    p.setColor(QPalette.ToolTipBase,     QColor(30, 30, 30))
    p.setColor(QPalette.ToolTipText,     QColor(220, 220, 220))
    p.setColor(QPalette.Text,            QColor(220, 220, 220))
    p.setColor(QPalette.Button,          QColor(60, 60, 65))
    p.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    p.setColor(QPalette.BrightText,      QColor(255, 80, 80))
    p.setColor(QPalette.Highlight,       QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    return p


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Thermal Annotation Tool")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())

    window = AppWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
