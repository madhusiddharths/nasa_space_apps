"""Mars surface temperature for any place, season and time of day.

Ground temperature on Mars is set almost entirely by four things: latitude, season,
time of day, and what the ground is made of. Two NASA maps describe the ground:

  thermal inertia  2001 Mars Odyssey THEMIS (USGS quantitative mosaic, 100 m/px).
                   Dust is ~50-150, sand ~200-400, rock and bedrock 600+.
                   Low inertia = scorching afternoons and bitter nights.
  albedo           Mars Global Surveyor TES (7.4 km/px). Dark ground absorbs more sun.

A thermal model (scripts/build_temperature_lut.py) turns those into temperature.
Its results are stored as a lookup table, so reads here are fast and need no solver.
Checked against Curiosity's REMS ground temperature sensor: see scripts/validate_temperature.py.

Same grid conventions as elevation.py: GCS_Mars_2000_Sphere (wkid 104971), lon -180..180
east positive, rows run north to south, values float32, NaN never appears (gaps are filled).

    import temperature
    box = (136.5, -6.0, 139.0, -4.0)                     # Gale: west, south, east, north
    t = temperature.read_temperature(*box, ls=90, local_time=14, shape=(593, 741))   # kelvin
    coldest = temperature.read_temperature(*box, ls=90, stat="min", shape=(593, 741))

Ls is the solar longitude, Mars' season angle: 0 = northern spring equinox,
90 = northern summer solstice, 180 = autumn equinox, 270 = winter solstice (and dust season).
local_time is local true solar time in hours (12 = Sun highest).

Committed data (temperature_data/) covers the planet at 16 px/deg (3.7 km). For 100 m
detail, download THEMIS tiles into data/temperature/ (see DATA_SOURCES.md); they are used
automatically wherever they exist.
"""
import io
import math
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).parent
LUT_PATH = ROOT / "temperature_data/surface_temperature_lut.npz"
INERTIA_PATH = ROOT / "temperature_data/mars_thermal_inertia_16ppd.tif"
ALBEDO_PATH = ROOT / "temperature_data/mars_albedo_8ppd.tif"
THEMIS_DIR = ROOT / "data/temperature"       # optional 100 m tiles, 60 deg x 30 deg each
THEMIS_NAME = "THEMIS_TI_Mosaic_Quant_{lat}{lon:03d}E_100mpp.tif"
M_PER_DEG = math.pi * 3396190.0 / 180
COARSE_PPD = 16
STATS = ("min", "max", "mean", "range")

_lock = threading.Lock()                     # one GDAL handle per file, shared by the server's threads
_open = {}
_lut = None


def _dataset(path):
    if path not in _open:
        _open[path] = rasterio.open(path)
    return _open[path]


def _table():
    global _lut
    if _lut is None:
        z = np.load(LUT_PATH)
        _lut = {
            "kelvin": z["kelvin_x10"].astype(np.float32) / 10,   # [season, hour, lat, inertia, albedo]
            "lat": z["lat"], "log_inertia": np.log(z["inertia"]), "albedo": z["albedo"],
        }
    return _lut


# --- Ground properties ---

def _themis_tiles(west, south, east, north):
    """(path, lon0, lat_south) of downloaded 100 m tiles overlapping a lon/lat box."""
    if not THEMIS_DIR.is_dir():
        return []
    found = []
    for lat0 in (-60, -30, 0, 30):
        for lon0 in range(0, 360, 60):
            w = lon0 if lon0 < 180 else lon0 - 360          # tiles use 0..360 E
            if w < east and w + 60 > west and lat0 < north and lat0 + 30 > south:
                name = THEMIS_NAME.format(lat=f"{abs(lat0):02d}{'N' if lat0 >= 0 else 'S'}", lon=lon0)
                if (THEMIS_DIR / name).exists():
                    found.append((THEMIS_DIR / name, w, lat0))
    return found


def _paste_themis(inertia, west, south, east, north):
    """Overwrite a coarse inertia grid with 100 m THEMIS values where a tile has data."""
    rows, cols = inertia.shape
    dlon, dlat = (east - west) / cols, (north - south) / rows
    for path, tile_west, tile_south in _themis_tiles(west, south, east, north):
        c0 = max(0, math.floor((tile_west - west) / dlon))
        c1 = min(cols, math.ceil((tile_west + 60 - west) / dlon))
        r0 = max(0, math.floor((north - tile_south - 30) / dlat))
        r1 = min(rows, math.ceil((north - tile_south) / dlat))
        if c1 <= c0 or r1 <= r0:
            continue
        # The part of the output grid inside this tile, as a pixel window of the tile (metres, 100 m/px).
        left = (west + c0 * dlon - tile_west) * M_PER_DEG / 100
        top = (tile_south + 30 - (north - r0 * dlat)) * M_PER_DEG / 100
        window = Window(left, top, (c1 - c0) * dlon * M_PER_DEG / 100, (r1 - r0) * dlat * M_PER_DEG / 100)
        with _lock:
            data = _dataset(path).read(1, window=window, out_shape=(r1 - r0, c1 - c0), boundless=True,
                                       fill_value=0, resampling=Resampling.average, masked=True)
        data = np.ma.filled(data, 0)
        good = (data > 5) & (data < 5000)
        inertia[r0:r1, c0:c1][good] = data[good]


def read_ground(west, south, east, north, shape=None):
    """Thermal inertia (J m-2 K-1 s-1/2) and albedo (0-1) for a lon/lat box, as two float32 grids.

    shape=(rows, cols); default is the committed map's 16 px/deg. Grids finer than that
    pick up 100 m THEMIS detail wherever a tile has been downloaded into data/temperature/.
    """
    if shape is None:
        shape = (max(1, round((north - south) * COARSE_PPD)), max(1, round((east - west) * COARSE_PPD)))
    with _lock:
        ti = _dataset(INERTIA_PATH)
        inertia = ti.read(1, window=from_bounds(west, south, east, north, ti.transform), out_shape=shape,
                          boundless=True, resampling=Resampling.bilinear).astype(np.float32)
        al = _dataset(ALBEDO_PATH)
        albedo = al.read(1, window=from_bounds(west, south, east, north, al.transform), out_shape=shape,
                         boundless=True, resampling=Resampling.bilinear).astype(np.float32) / 10000
    inertia[inertia <= 0] = 200          # only outside -180..180 / -90..90
    albedo[albedo <= 0] = 0.2
    if (north - south) / shape[0] < 1 / COARSE_PPD:
        _paste_themis(inertia, west, south, east, north)
    return inertia, albedo


# --- Lookup ---

def _cyclic(table, position):
    """Linear interpolation along axis 0 of a table that wraps around."""
    n = table.shape[0]
    i = math.floor(position) % n
    f = position - math.floor(position)
    return table[i] * (1 - f) + table[(i + 1) % n] * f


def _season_table(ls, local_time=None, stat=None):
    """The lookup table cut down to [lat, inertia, albedo] for one season and time (or daily statistic)."""
    kelvin = _table()["kelvin"]
    day = _cyclic(kelvin, (ls % 360) / 360 * kelvin.shape[0] - 0.5)      # [hour, lat, inertia, albedo]
    if stat is None:
        return _cyclic(day, local_time % 24)
    if stat not in STATS:
        raise ValueError(f"stat must be one of {STATS}")
    if stat == "range":
        return day.max(axis=0) - day.min(axis=0)
    return getattr(day, stat)(axis=0)


def _fraction(axis, values):
    """Index of the cell below each value and the fraction of the way to the next one."""
    pos = np.interp(values, axis, np.arange(axis.size))
    lower = np.minimum(pos.astype(np.intp), axis.size - 2)
    return lower, (pos - lower).astype(np.float32)


def _lookup(table, lats, inertia, albedo):
    """Trilinear interpolation of a [lat, inertia, albedo] table. lats is one value per grid row."""
    lut = _table()
    i, fi = _fraction(lut["lat"], np.asarray(lats, dtype=np.float64))
    j, fj = _fraction(lut["log_inertia"], np.log(np.maximum(inertia, 1)))
    k, fk = _fraction(lut["albedo"], albedo)
    i, fi = i[:, None], fi[:, None]
    out = np.zeros(inertia.shape, dtype=np.float32)
    for di, wi in ((0, 1 - fi), (1, fi)):
        for dj, wj in ((0, 1 - fj), (1, fj)):
            for dk, wk in ((0, 1 - fk), (1, fk)):
                out += wi * wj * wk * table[i + di, j + dj, k + dk]
    return out


def read_temperature(west, south, east, north, ls=0.0, local_time=14.0, shape=None, stat=None):
    """Surface temperature in kelvin for a lon/lat box, as float32 rows running north to south.

    ls          season, solar longitude in degrees (0-360)
    local_time  local true solar time in hours (0-24); the same clock time is used across the box
    stat        instead of one time of day: "min", "max", "mean" or "range" over the whole day
    shape       (rows, cols); default 16 px/deg. Use the same box and shape as elevation.read_elevation
                to line the two up for routing.
    """
    inertia, albedo = read_ground(west, south, east, north, shape)
    rows = inertia.shape[0]
    lats = north - (np.arange(rows) + 0.5) * (north - south) / rows
    return _lookup(_season_table(ls, local_time, stat), np.clip(lats, -90, 90), inertia, albedo)


def diurnal_cycle(lon, lat, ls=0.0):
    """Everything about one spot: its ground properties and its temperature for each hour 0-23."""
    d = 0.5 / 592.75                       # one 100 m pixel
    inertia, albedo = read_ground(lon - d, lat - d, lon + d, lat + d, shape=(1, 1))
    kelvin = _table()["kelvin"]
    day = _cyclic(kelvin, (ls % 360) / 360 * kelvin.shape[0] - 0.5)
    hours = [float(_lookup(day[h], [lat], inertia, albedo)[0, 0]) for h in range(24)]
    return {
        "lon": lon, "lat": lat, "ls": ls,
        "thermal_inertia": float(inertia[0, 0]), "albedo": float(albedo[0, 0]),
        "kelvin_by_hour": [round(v, 1) for v in hours],
        "min": round(min(hours), 1), "max": round(max(hours), 1),
    }


# --- Map tiles for the 3D viewer ---
# Same tiling scheme as elevation.tile: origin (-180, 90), level 0 is two 180-degree tiles.
TILE_SIZE = 512
COLOR_RANGES = {None: (150.0, 300.0), "min": (150.0, 300.0), "max": (150.0, 300.0),
                "mean": (150.0, 300.0), "range": (0.0, 120.0)}
# Colour stops, cold to hot (matched by the legend in web/index.html).
RAMP = np.array([[13, 8, 135], [84, 2, 163], [139, 10, 165], [185, 50, 137], [219, 92, 104],
                 [244, 136, 73], [254, 188, 43], [240, 249, 33]], dtype=np.float32)


def colorize(values, low, high):
    """RGB uint8 image for a grid of values, on the RAMP between low and high."""
    pos = np.clip((values - low) / (high - low), 0, 1) * (len(RAMP) - 1)
    i = np.minimum(pos.astype(np.intp), len(RAMP) - 2)
    f = (pos - i)[..., None]
    return (RAMP[i] * (1 - f) + RAMP[i + 1] * f).astype(np.uint8)


def tile_png(level, row, col, ls=0.0, local_time=14.0, stat=None, low=None, high=None):
    """One 512 x 512 PNG map tile of surface temperature.

    low/high (kelvin) set the ends of the colour ramp; default is COLOR_RANGES, which fits the whole planet.
    """
    from PIL import Image

    span = 180 / 2**level
    west, north = -180 + col * span, 90 - row * span
    values = read_temperature(west, north - span, west + span, north, ls=ls, local_time=local_time,
                              shape=(TILE_SIZE, TILE_SIZE), stat=stat)
    default_low, default_high = COLOR_RANGES[stat]
    low = default_low if low is None else low
    high = default_high if high is None or high <= low else high
    buf = io.BytesIO()
    Image.fromarray(colorize(values, low, high)).save(buf, format="PNG")
    return buf.getvalue()


def value_range(west, south, east, north, ls=0.0, local_time=14.0, stat=None):
    """2nd and 98th percentile of temperature in a box: a colour range that shows local contrast."""
    values = read_temperature(west, south, east, north, ls=ls, local_time=local_time, stat=stat, shape=(256, 256))
    low, high = np.percentile(values, [2, 98])
    return float(np.floor(low)), float(np.ceil(max(high, low + 2)))
