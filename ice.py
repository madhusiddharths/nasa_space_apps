"""Water ice: how deep the shallowest ice is, surface and buried combined, 3 km/px.

Two sources are merged into one grid of depth classes:
  Surface ice  The polar ice units of the USGS global geologic map (Tanaka et al. 2014):
               lApc (residual polar cap) and Apu (polar layered deposits, water ice).
  Buried ice   SWIM ice-consistency maps (Morgan & Putzig et al. 2025) for 0-1 m, 1-5 m
               and >5 m depth. A score of 0.3 or more counts as ice, the cut-off SWIM's
               own maps use. The class is the shallowest depth range that reaches it.

Limits: SWIM is a consistency score from several orbiter datasets, not a measured amount
of ice, and it covers 60S to 60N only. Between 60 degrees and the polar units nothing is
mapped, although shallow ground ice is known there (Phoenix lander, 68N). The southern
residual cap is CO2 ice over water ice.

GIS facts about the grid (see DATA_SOURCES.md for the shared conventions):
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        7200 x 3600 px, 0.05 deg/px (3 km at the equator), same as the SWIM files
  Values      int8 index into CLASSES, -1 where no ice is mapped
"""
import io
import json
import threading
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_origin

DATA_DIR = Path(__file__).parent / "data/water_ice"
ROWS, COLS = 3600, 7200
DEG_PER_PX = 0.05
ICE_SCORE = 0.3  # SWIM consistency at or above this counts as ice

# Depth classes, shallowest first: (label, map colour, SWIM file or None for surface ice).
# White for exposed ice, then light-to-dark ColorBrewer Blues as the ice gets deeper.
CLASSES = [
    ("On the surface (polar ice)", (255, 255, 255), None),
    ("Within 1 m of the surface", (158, 202, 225), "SWIM4MIM_Ci_0_1.tif"),
    ("1 to 5 m deep", (66, 146, 198), "SWIM4MIM_Ci_1_5.tif"),
    ("Deeper than 5 m", (8, 69, 148), "SWIM4MIM_Ci_5.tif"),
]
# One RGBA row per class, plus a transparent last row that class -1 (no ice) indexes.
_PALETTE = np.array([rgb + (255,) for _, rgb, _ in CLASSES] + [(0, 0, 0, 0)], np.uint8)

_grid = None
_lock = threading.Lock()


def _build():
    """The global class grid: surface ice wins, then the shallowest SWIM depth with ice."""
    grid = np.full((ROWS, COLS), -1, np.int8)
    swim_rows = slice(int(30 / DEG_PER_PX), int(150 / DEG_PER_PX))  # 60N..60S
    for index in range(len(CLASSES) - 1, 0, -1):  # deepest first, shallower overwrites
        with rasterio.open(DATA_DIR / CLASSES[index][2]) as src:
            score = src.read(1)
        grid[swim_rows][score >= ICE_SCORE] = index
    polar = json.loads((DATA_DIR / "polar_surface_ice.geojson").read_text())
    surface = rasterize(
        [feature["geometry"] for feature in polar["features"]],
        out_shape=(ROWS, COLS), transform=from_origin(-180, 90, DEG_PER_PX, DEG_PER_PX),
    )
    grid[surface == 1] = 0
    return grid


def read_ice_class(west, south, east, north, shape=None):
    """Index into CLASSES for a lon/lat box (0 = surface ice ... 3 = deeper than 5 m),
    -1 where no ice is mapped. Rows run north to south.

    Same arguments as elevation.read_elevation, so layers can be put on one grid:
    shape=(rows, cols) samples to that size (nearest cell), default is native 3 km.
    """
    global _grid
    with _lock:
        if _grid is None:
            _grid = _build()
    rows, cols = shape or (round((north - south) / DEG_PER_PX), round((east - west) / DEG_PER_PX))
    lats = north - (np.arange(rows) + 0.5) * (north - south) / rows
    lons = west + (np.arange(cols) + 0.5) * (east - west) / cols
    r = np.clip(((90 - lats) / DEG_PER_PX).astype(int), 0, ROWS - 1)
    c = np.clip(((lons + 180) / DEG_PER_PX).astype(int), 0, COLS - 1)
    return _grid[r[:, None], c[None, :]]


# --- Map tiles for the 3D viewer (same tiling scheme as the CTX imagery) ---
TILE_PX = 512


def tile_png(level, row, col):
    """One viewer tile, coloured by depth class; transparent where no ice is mapped."""
    span = 180 / 2**level
    west = -180 + col * span
    north = 90 - row * span
    classes = read_ice_class(west, north - span, west + span, north, shape=(TILE_PX, TILE_PX))
    out = io.BytesIO()
    Image.fromarray(_PALETTE[classes]).save(out, "PNG")
    return out.getvalue()


def legend():
    """Class labels and colours for the viewer's legend."""
    return [{"label": label, "color": "#%02x%02x%02x" % rgb} for label, rgb, _ in CLASSES]
