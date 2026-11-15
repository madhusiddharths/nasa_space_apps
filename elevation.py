"""Local Mars elevation: USGS HRSC + MOLA blended DEM v2, 200 m/px.

GIS facts about the file (every other layer should be put on the same grid):
  CRS         GCS_Mars_2000_Sphere (Esri wkid 104971), plain lon/lat degrees
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        106694 x 53347 px, 0.003374120830641 deg/px (200 m at the equator)
  Storage     the USGS file is uncompressed rows as wide as the planet, with its reduced
              copies in a separate .ovr file (15 GB together)
  Values      int16 metres above the MOLA areoid, range -8528..21226, nodata -32768
  Sphere      radius 3,396,190 m, so 1 deg of latitude = 59,274.7 m everywhere
              and 1 deg of longitude = 59,274.7 * cos(lat) m
"""
import math
import os
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

import tiles

SOURCE_DEM_PATH = Path(__file__).parent / "data/elevation/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"
COG_DEM_PATH = SOURCE_DEM_PATH.with_name("Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif")
# The copy is the same heights in a tiled, compressed file a quarter of the size, written by
# scripts/build_elevation_cog.py. It is used when it is there; the original works without it.
LOCAL_DEM_PATH = COG_DEM_PATH if COG_DEM_PATH.exists() else SOURCE_DEM_PATH
# MARS_DEM (optional) says the elevation file is somewhere else: another path, or a file in a
# storage bucket that is read over the network, "/vsigs/<bucket>/<file>". Over a network
# only the tiled copy is usable; the original takes hundreds of megabytes per read. See DEPLOY.md.
DEM_PATH = os.environ.get("MARS_DEM") or LOCAL_DEM_PATH
DEM_AVAILABLE = bool(os.environ.get("MARS_DEM")) or LOCAL_DEM_PATH.exists()
MARS_RADIUS_M = 3396190.0
M_PER_DEG = math.pi * MARS_RADIUS_M / 180
NODATA = -32768

_handles = threading.local()  # one GDAL handle per server thread, so reads run side by side


def read_elevation(west, south, east, north, shape=None, resampling=Resampling.bilinear):
    """Elevation in metres for a lon/lat box, as float32 rows running north to south.

    shape=(rows, cols) resamples to that size (coarse sizes read the file's built-in
    overviews, so whole-planet reads are fast). Default is native 200 m resolution.
    Nodata cells are NaN.
    """
    if not hasattr(_handles, "dem"):
        _handles.dem = rasterio.open(DEM_PATH)
    dem = _handles.dem
    window = from_bounds(west, south, east, north, dem.transform)
    data = dem.read(1, window=window, out_shape=shape, resampling=resampling)
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


# --- Terrain tiles for the 3D viewer (tiling scheme in tiles.py) ---
TILE_SAMPLES = 257  # 256 intervals; first and last sample sit on the tile edges


def tile(level, row, col):
    """Float32 elevation samples (257 x 257) for one viewer terrain tile."""
    west, south, east, north = tiles.bounds(level, row, col)
    half = (east - west) / (TILE_SAMPLES - 1) / 2  # half a sample, so samples land on the edges
    data = read_elevation(max(west - half, -180), max(south - half, -90),
                          min(east + half, 180), min(north + half, 90),
                          shape=(TILE_SAMPLES, TILE_SAMPLES))
    return np.nan_to_num(data, nan=NODATA)
