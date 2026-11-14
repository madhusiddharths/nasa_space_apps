"""Local Mars elevation: USGS HRSC + MOLA blended DEM v2, 200 m/px.

GIS facts about the file (every other layer should be put on the same grid):
  CRS         GCS_Mars_2000_Sphere (Esri wkid 104971), plain lon/lat degrees
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        106694 x 53347 px, 0.003374120830641 deg/px (200 m at the equator)
  Values      int16 metres above the MOLA areoid, range -8528..21226, nodata -32768
  Sphere      radius 3,396,190 m, so 1 deg of latitude = 59,274.7 m everywhere
              and 1 deg of longitude = 59,274.7 * cos(lat) m
"""
import math
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

DEM_PATH = Path(__file__).parent / "data/elevation/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"
MARS_RADIUS_M = 3396190.0
M_PER_DEG = math.pi * MARS_RADIUS_M / 180
NODATA = -32768

_dem = None
_lock = threading.Lock()  # one GDAL handle shared by the server's worker threads


def read_elevation(west, south, east, north, shape=None):
    """Elevation in metres for a lon/lat box, as float32 rows running north to south.

    shape=(rows, cols) resamples to that size (coarse sizes read the file's built-in
    overviews, so whole-planet reads are fast). Default is native 200 m resolution.
    Nodata cells are NaN.
    """
    global _dem
    with _lock:
        if _dem is None:
            _dem = rasterio.open(DEM_PATH)
        window = from_bounds(west, south, east, north, _dem.transform)
        data = _dem.read(1, window=window, out_shape=shape, resampling=Resampling.bilinear)
    data = data.astype(np.float32)
    data[data == NODATA] = np.nan
    return data


def slope_degrees(elevation, south, north, west, east):
    """Slope in degrees for a grid returned by read_elevation over the same box.

    Uses true ground distances: north-south cell size is constant, east-west cell
    size shrinks by cos(latitude).
    """
    rows, cols = elevation.shape
    dlat = (north - south) / rows
    dlon = (east - west) / cols
    lats = north - (np.arange(rows) + 0.5) * dlat
    dy = dlat * M_PER_DEG
    dx = dlon * M_PER_DEG * np.cos(np.radians(lats))[:, None]
    dz_dy, dz_dx = np.gradient(elevation)
    return np.degrees(np.arctan(np.hypot(dz_dx / dx, dz_dy / dy)))


# --- Terrain tiles for the 3D viewer ---
# Same tiling scheme as the CTX imagery: origin (-180, 90), level 0 is two
# 180-degree tiles, each level halves the tile span.
TILE_SAMPLES = 257  # 256 intervals; first and last sample sit on the tile edges


def tile(level, row, col):
    """Float32 elevation samples (257 x 257) for one viewer terrain tile."""
    span = 180 / 2**level
    half = span / (TILE_SAMPLES - 1) / 2
    west = max(-180 + col * span - half, -180)
    east = min(-180 + (col + 1) * span + half, 180)
    north = min(90 - row * span + half, 90)
    south = max(90 - (row + 1) * span - half, -90)
    data = read_elevation(west, south, east, north, shape=(TILE_SAMPLES, TILE_SAMPLES))
    return np.nan_to_num(data, nan=NODATA)
