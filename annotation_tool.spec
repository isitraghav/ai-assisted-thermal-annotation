# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Thermal Annotation Tool.

Build with (from project root):
    python build_exe.py
  or directly:
    pyinstaller --clean -y annotation_tool.spec

Output: dist/ThermalAnnotationTool/ThermalAnnotationTool  (Linux)
        dist/ThermalAnnotationTool/ThermalAnnotationTool.exe  (Windows)
"""
import sys as _sys
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

project_root = Path(SPECPATH)

# ---------------------------------------------------------------------------
# Collect complex geospatial / binary packages
# ---------------------------------------------------------------------------
datas_r,   bins_r,   hidden_r   = collect_all('rasterio')
datas_po,  bins_po,  hidden_po  = collect_all('pyogrio')
datas_pp,  bins_pp,  hidden_pp  = collect_all('pyproj')
datas_sh,  bins_sh,  hidden_sh  = collect_all('shapely')
datas_gp,  bins_gp,  hidden_gp  = collect_all('geopandas')
datas_pil, bins_pil, hidden_pil = collect_all('PIL')
datas_qt,  bins_qt,  hidden_qt  = collect_all('PyQt5')

# ---------------------------------------------------------------------------
# DJI Thermal SDK shared libraries → bundled into dji_sdk_libs/
# ---------------------------------------------------------------------------
if _sys.platform == "win32":
    dji_sdk_src = project_root / "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/windows/release_x64"
    dji_binaries = [(str(f), "dji_sdk_libs") for f in dji_sdk_src.glob("*.dll")]
else:
    dji_sdk_src = project_root / "dji_thermal_sdk_v1.8_20250829/tsdk-core/lib/linux/release_x64"
    dji_binaries = [(str(f), "dji_sdk_libs") for f in dji_sdk_src.glob("*.so*")]
dji_datas = [(str(f), "dji_sdk_libs") for f in dji_sdk_src.glob("*.ini")]

# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------
all_binaries = (
    bins_r + bins_po + bins_pp + bins_sh + bins_gp + bins_pil + bins_qt +
    dji_binaries
)
all_datas = (
    datas_r + datas_po + datas_pp + datas_sh + datas_gp + datas_pil + datas_qt +
    dji_datas
)
all_hidden = (
    hidden_r + hidden_po + hidden_pp + hidden_sh + hidden_gp + hidden_pil + hidden_qt +
    collect_submodules('annotation_tool') +
    [
        'extractor',
        'dji_thermal',
        'piexif',
        'tqdm',
        'numpy',
        'pkg_resources',
    ]
)

a = Analysis(
    [str(project_root / 'annotation_tool/main.py')],
    pathex=[str(project_root)],          # makes extractor.py / dji_thermal.py importable
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'IPython', 'jupyter', 'tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ThermalAnnotationTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # keep console so errors are visible on first launch
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ThermalAnnotationTool',
)
