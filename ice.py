"""Water ice: how deep the shallowest ice is, surface and buried combined, 3 km/px.

Two sources are merged into one grid of depth classes:
  Surface ice  The polar ice units of the USGS global geologic map (Tanaka et al. 2014):
               lApc (residual polar cap) and Apu (polar layered deposits, water ice).
  Buried ice   SWIM ice-consistency maps (Morgan & Putzig et al. 2025) for 0-1 m, 1-5 m
               and >5 m depth. A score of 0.3 or more counts as ice, the cut-off SWIM's
               own maps use. The class is the shallowest depth range that reaches it.

For display the SWIM scores are smoothed over about 24 km (Gaussian, sigma 8 px) before
the cut-off is applied, which rounds the square footprints of SWIM's coarser inputs.
Every ice pixel the smoothing would drop (small patches, thin streaks, corners) is then
added back at its own size with a soft edge, so no ice in the source maps is left out.
Map tiles fade between classes and are shaded with the terrain relief.

The merging and smoothing are done once, by scripts/build_ice_grid.py, and saved as
ice_data/mars_ice_weights_20ppd.tif (in git, 9 MB). This module only reads the window of
that file a tile or a box needs, as elevation.py and firmness.py do, so the first ice
tile is as quick as any other and nothing planet-sized is held in memory.

Limits: SWIM is a consistency score from several orbiter datasets, not a measured amount
of ice, and it covers 60S to 60N only. Between 60 degrees and the polar units nothing is
mapped, although shallow ground ice is known there (Phoenix lander, 68N). The southern
residual cap is CO2 ice over water ice.

GIS facts about the grid (see DATA_SOURCES.md for the shared conventions):
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        7200 x 3600 px, 0.05 deg/px (3 km at the equator), same as the SWIM files
  Bands       one per class of CLASSES; 0..255 for a weight 0..1 that ice is present
              (128 = SWIM score 0.3). The file carries reduced copies of itself (1/2 to
              1/16 size) for zoomed-out reads.
              read_ice_class() turns the weights into an int8 index into CLASSES, -1 for none
"""
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

import elevation
import tiles
from tiles import TILE_PX

GRID_PATH = Path(__file__).parent / "ice_data/mars_ice_weights_20ppd.tif"
ROWS, COLS = 3600, 7200
DEG_PER_PX = 0.05
ICE_SCORE = 0.3  # SWIM consistency at or above this counts as ice

# Depth classes, shallowest first: (label, map colour, SWIM file or None for surface ice).
# The SWIM files are read only by scripts/build_ice_grid.py.
# White for exposed ice, then light-to-dark ColorBrewer Blues as the ice gets deeper.
CLASSES = [
    ("On the surface (polar ice)", (255, 255, 255), None),
    ("Within 1 m of the surface", (158, 202, 225), "SWIM4MIM_Ci_0_1.tif"),
    ("1 to 5 m deep", (66, 146, 198), "SWIM4MIM_Ci_1_5.tif"),
    ("Deeper than 5 m", (8, 69, 148), "SWIM4MIM_Ci_5.tif"),
]
_COLOURS = np.array([rgb for _, rgb, _ in CLASSES], np.float32)

_grid = None
_lock = threading.Lock()  # one GDAL handle shared by the server's worker threads


def read_weights(west, south, east, north, shape, resampling=Resampling.bilinear):
    """Ice-presence weight 0..1 of each class for a lon/lat box: float32 (class, rows, cols),
    rows running north to south. Coarse shapes read the file's reduced copies."""
    global _grid
    with _lock:
        if _grid is None:
            if not GRID_PATH.exists():
                raise FileNotFoundError(f"{GRID_PATH} is missing; build it with scripts/build_ice_grid.py")
            _grid = rasterio.open(GRID_PATH)
        window = from_bounds(west, south, east, north, _grid.transform)
        data = _grid.read(window=window, out_shape=(len(CLASSES),) + tuple(shape), resampling=resampling)
    return data.astype(np.float32) / 255


def read_ice_class(west, south, east, north, shape=None):
    """Index into CLASSES for a lon/lat box (0 = surface ice ... 3 = deeper than 5 m),
    -1 where no ice is mapped. Rows run north to south.

    Same arguments as elevation.read_elevation, so layers can be put on one grid:
    shape=(rows, cols) samples to that size (nearest cell), default is native 3 km.
    """
    shape = shape or (round((north - south) / DEG_PER_PX), round((east - west) / DEG_PER_PX))
    present = read_weights(west, south, east, north, shape, Resampling.nearest) >= 0.5
    return np.where(present.any(axis=0), present.argmax(axis=0), -1).astype(np.int8)


# --- Map tiles for the 3D viewer (tiling scheme in tiles.py) ---
RELIEF = 4  # slope exaggeration for the relief shading


def _hillshade(west, south, east, north, rows, cols):
    """Relief shading factor around 1 (flat ground = 1), light from the north-west."""
    z = elevation.read_elevation(west, max(south, -90), east, min(north, 90), shape=(rows, cols))
    lats, _ = tiles.cell_centres(west, south, east, north, rows, cols)
    dy = (north - south) / rows * elevation.M_PER_DEG
    # East-west spacing shrinks towards the poles; capped at 0.25 so the elevation data's
    # along-track noise is not amplified into stripes there.
    dx = (east - west) / cols * elevation.M_PER_DEG * np.maximum(np.cos(np.radians(lats)), 0.25)[:, None]
    dz_dy, dz_dx = np.gradient(np.nan_to_num(z))
    # Slopes are exaggerated so gentle Martian relief still reads.
    gx, gy = RELIEF * dz_dx / dx, RELIEF * dz_dy / dy  # east-ward and south-ward gradients
    # Surface normal (-gx, gy, 1) dotted with a unit light vector from the north-west, 45 deg up.
    shade = (0.5 * gx - 0.5 * gy + 0.7071) / np.sqrt(gx**2 + gy**2 + 1)
    return np.clip(shade / 0.7071, 0.35, 1.3)


def tile_png(level, row, col):
    """One viewer tile: depth-class colours that fade into each other and into nothing,
    shaded with the terrain relief so the colour sits in the landscape."""
    west, south, east, north = tiles.bounds(level, row, col)

    w = read_weights(west, south, east, north, (TILE_PX, TILE_PX))

    # Composite deepest first, so shallower ice covers deeper ice.
    rgb = np.zeros((TILE_PX, TILE_PX, 3), np.float32)
    alpha = np.zeros((TILE_PX, TILE_PX), np.float32)
    for index in range(len(CLASSES) - 1, -1, -1):
        wi = w[index][..., None]
        rgb = _COLOURS[index] * wi + rgb * (1 - wi)
        alpha = w[index] + alpha * (1 - w[index])
    if not alpha.any():
        return tiles.png(np.zeros((TILE_PX, TILE_PX, 4), np.uint8))
    rgb /= np.maximum(alpha, 1e-6)[..., None]
    rgb *= _hillshade(west, south, east, north, TILE_PX, TILE_PX)[..., None]
    return tiles.png(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8))


def legend():
    """Class labels and colours for the viewer's legend."""
    return [{"label": label, "color": tiles.hex_color(rgb)} for label, rgb, _ in CLASSES]
