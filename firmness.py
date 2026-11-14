"""Ground firmness from thermal inertia: MGS TES nightside map (Putzig & Mellon 2007), 3 km/px.

Thermal inertia is how slowly the ground changes temperature. Loose dust heats and cools
fast (low values); packed sand, cemented soil and rock hold heat (high values). NASA landing
site selection treats ground below 100 as possibly unable to bear a load.

Limits: the measurement senses only the top few centimetres, averaged over 3 km. Poleward
of about 60 degrees the values are affected by ice and seasonal frost, and there is no data
beyond 87 degrees.

GIS facts about the file (see DATA_SOURCES.md for the shared conventions):
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        7200 x 3600 px, 0.05 deg/px (3 km at the equator)
  Values      big-endian int16, J m^-2 K^-1 s^-1/2 ("tiu"), range 5..5000, 0 = nodata
"""
import io
import threading
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

TI_PATH = Path(__file__).parent / "data/thermal_inertia/global_ti_night_2007.img"
ROWS, COLS = 3600, 7200
NODATA = 0

# Firmness classes: (upper bound in tiu, what the ground is like, map colour).
# Bounds follow the particle-size reading of thermal inertia (dust < 100, sand 200-350,
# bedrock > 1200); colours are ColorBrewer RdYlBu, which is colour-blind safe.
CLASSES = [
    (100, "Loose dust, may not bear weight", (215, 48, 39)),
    (200, "Dusty ground or fine sand, soft", (252, 141, 89)),
    (350, "Sand and crusted soil, firm", (254, 224, 144)),
    (600, "Coarse sand, pebbles, hard crust", (224, 243, 248)),
    (1200, "Rocky ground, hard", (145, 191, 219)),
    (np.inf, "Bedrock, or ice near the poles", (69, 117, 180)),
]
_BOUNDS = [upper for upper, _, _ in CLASSES[:-1]]
# One RGBA row per class, plus a transparent last row that class -1 (nodata) indexes.
_PALETTE = np.array([rgb + (255,) for _, _, rgb in CLASSES] + [(0, 0, 0, 0)], np.uint8)

_ti = None
_lock = threading.Lock()  # one GDAL handle shared by the server's worker threads


def _open():
    """The raw PDS image wrapped as an in-memory GeoTIFF, so GDAL does the resampling."""
    raw = np.fromfile(TI_PATH, ">i2").reshape(ROWS, COLS).astype(np.int16)
    memory = MemoryFile()
    with memory.open(driver="GTiff", height=ROWS, width=COLS, count=1, dtype="int16",
                     nodata=NODATA, transform=from_origin(-180, 90, 360 / COLS, 180 / ROWS)) as dst:
        dst.write(raw, 1)
    return memory.open()


def read_thermal_inertia(west, south, east, north, shape=None, resampling=Resampling.bilinear):
    """Thermal inertia in tiu for a lon/lat box, as float32 rows running north to south.

    Same arguments as elevation.read_elevation, so both layers can be put on one grid:
    shape=(rows, cols) resamples to that size, default is native 3 km resolution.
    Nodata cells are NaN.
    """
    global _ti
    with _lock:
        if _ti is None:
            _ti = _open()
        window = from_bounds(west, south, east, north, _ti.transform)
        data = _ti.read(1, window=window, out_shape=shape, resampling=resampling)
    data = data.astype(np.float32)
    data[data == NODATA] = np.nan
    return data


def firmness_class(thermal_inertia):
    """Index into CLASSES for each cell (0 = loosest ... 5 = most solid), -1 for nodata."""
    classes = np.digitize(thermal_inertia, _BOUNDS).astype(np.int8)
    classes[np.isnan(thermal_inertia)] = -1
    return classes


# --- Map tiles for the 3D viewer (same tiling scheme as the CTX imagery) ---
TILE_PX = 512


def tile_png(level, row, col):
    """One viewer tile, coloured by firmness class; transparent where there is no data."""
    span = 180 / 2**level
    west = -180 + col * span
    north = 90 - row * span
    ti = read_thermal_inertia(west, north - span, west + span, north, shape=(TILE_PX, TILE_PX))
    out = io.BytesIO()
    Image.fromarray(_PALETTE[firmness_class(ti)]).save(out, "PNG")
    return out.getvalue()


def legend():
    """Class ranges, descriptions and colours for the viewer's legend."""
    lower = [0] + _BOUNDS
    return [
        {
            "range": f"{lo}–{upper}" if upper != np.inf else f"over {lo}",
            "label": label,
            "color": "#%02x%02x%02x" % rgb,
        }
        for lo, (upper, label, rgb) in zip(lower, CLASSES)
    ]
