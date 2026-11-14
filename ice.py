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

Limits: SWIM is a consistency score from several orbiter datasets, not a measured amount
of ice, and it covers 60S to 60N only. Between 60 degrees and the polar units nothing is
mapped, although shallow ground ice is known there (Phoenix lander, 68N). The southern
residual cap is CO2 ice over water ice.

GIS facts about the grid (see DATA_SOURCES.md for the shared conventions):
  Extent      lon -180..180 (east positive), lat 90..-90 (row 0 is north)
  Size        7200 x 3600 px, 0.05 deg/px (3 km at the equator), same as the SWIM files
  Values      per class, a weight 0..1 that ice is present (0.5 = SWIM score 0.3);
              read_ice_class() turns these into an int8 index into CLASSES, -1 for none
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

import elevation

DATA_DIR = Path(__file__).parent / "data/water_ice"
ROWS, COLS = 3600, 7200
DEG_PER_PX = 0.05
ICE_SCORE = 0.3  # SWIM consistency at or above this counts as ice
SMOOTH_PX = 8  # Gaussian sigma for the SWIM scores, in 3 km pixels
EDGE_SCORE = 0.1  # score range over which a class fades in, centred on ICE_SCORE

# Depth classes, shallowest first: (label, map colour, SWIM file or None for surface ice).
# White for exposed ice, then light-to-dark ColorBrewer Blues as the ice gets deeper.
CLASSES = [
    ("On the surface (polar ice)", (255, 255, 255), None),
    ("Within 1 m of the surface", (158, 202, 225), "SWIM4MIM_Ci_0_1.tif"),
    ("1 to 5 m deep", (66, 146, 198), "SWIM4MIM_Ci_1_5.tif"),
    ("Deeper than 5 m", (8, 69, 148), "SWIM4MIM_Ci_5.tif"),
]
_COLOURS = np.array([rgb for _, rgb, _ in CLASSES], np.float32)

_weights = None  # (class, ROWS, COLS) uint8: 0..255 for ice-presence weight 0..1
_lock = threading.Lock()


def _blur(a, sigma):
    """Gaussian blur; wraps in longitude, repeats the edge rows in latitude."""
    r = int(3 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(a, ((r, r), (0, 0)), mode="edge")
    a = sum(w * padded[i:i + a.shape[0]] for i, w in enumerate(kernel))
    padded = np.pad(a, ((0, 0), (r, r)), mode="wrap")
    return sum(w * padded[:, i:i + a.shape[1]] for i, w in enumerate(kernel))


def _build():
    """Per-class ice-presence weights for the whole planet."""
    weights = np.zeros((len(CLASSES), ROWS, COLS), np.uint8)
    swim_rows = slice(int(30 / DEG_PER_PX), int(150 / DEG_PER_PX))  # 60N..60S
    for index in range(1, len(CLASSES)):
        with rasterio.open(DATA_DIR / CLASSES[index][2]) as src:
            score = src.read(1)
        ramp = np.clip((_blur(score, SMOOTH_PX) - ICE_SCORE) / EDGE_SCORE + 0.5, 0, 1)
        # Ice the smoothing lost, kept at its own size: a slight blur for a soft edge,
        # doubled so that even a single 3 km pixel still counts as ice.
        dropped = (score >= ICE_SCORE) & (ramp < 0.5)
        detail = np.clip(_blur(dropped.astype(np.float32), 0.7) * 2, 0, 1)
        weights[index, swim_rows] = np.round(np.maximum(ramp, detail) * 255)
    polar = json.loads((DATA_DIR / "polar_surface_ice.geojson").read_text())
    surface = rasterize(
        [feature["geometry"] for feature in polar["features"]],
        out_shape=(ROWS, COLS), transform=from_origin(-180, 90, DEG_PER_PX, DEG_PER_PX),
    )
    # Soft edge, but never below 0.5 inside the mapped units, so thin slivers stay.
    surface = surface.astype(np.float32)
    weights[0] = np.round(np.maximum(_blur(surface, 1), surface * 0.5) * 255)
    return weights


def _weights_grid():
    global _weights
    with _lock:
        if _weights is None:
            _weights = _build()
    return _weights


def _cell_centres(west, south, east, north, rows, cols):
    """Fractional grid row and column of each cell centre of a lon/lat box."""
    lats = north - (np.arange(rows) + 0.5) * (north - south) / rows
    lons = west + (np.arange(cols) + 0.5) * (east - west) / cols
    return (90 - lats) / DEG_PER_PX - 0.5, (lons + 180) / DEG_PER_PX - 0.5


def read_ice_class(west, south, east, north, shape=None):
    """Index into CLASSES for a lon/lat box (0 = surface ice ... 3 = deeper than 5 m),
    -1 where no ice is mapped. Rows run north to south.

    Same arguments as elevation.read_elevation, so layers can be put on one grid:
    shape=(rows, cols) samples to that size (nearest cell), default is native 3 km.
    """
    rows, cols = shape or (round((north - south) / DEG_PER_PX), round((east - west) / DEG_PER_PX))
    r, c = _cell_centres(west, south, east, north, rows, cols)
    r = np.clip(np.round(r).astype(int), 0, ROWS - 1)
    c = np.round(c).astype(int) % COLS
    present = _weights_grid()[:, r[:, None], c[None, :]] >= 128
    return np.where(present.any(axis=0), present.argmax(axis=0), -1).astype(np.int8)


# --- Map tiles for the 3D viewer (same tiling scheme as the CTX imagery) ---
TILE_PX = 512
RELIEF = 4  # slope exaggeration for the relief shading


def _hillshade(west, south, east, north, rows, cols):
    """Relief shading factor around 1 (flat ground = 1), light from the north-west."""
    z = elevation.read_elevation(west, max(south, -90), east, min(north, 90), shape=(rows, cols))
    lats = north - (np.arange(rows) + 0.5) * (north - south) / rows
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
    span = 180 / 2**level
    west = -180 + col * span
    north = 90 - row * span
    south = north - span

    # Bilinear sample of the weight grids at the tile's pixel centres.
    r, c = _cell_centres(west, south, west + span, north, TILE_PX, TILE_PX)
    r = np.clip(r, 0, ROWS - 1)
    r0 = np.minimum(r.astype(int), ROWS - 2)
    c0 = np.floor(c).astype(int)
    fr = (r - r0)[None, :, None]
    fc = (c - c0)[None, None, :]
    grid = _weights_grid()
    rows0, rows1 = r0[:, None], r0[:, None] + 1
    cols0, cols1 = c0[None, :] % COLS, (c0[None, :] + 1) % COLS
    w = ((grid[:, rows0, cols0] * (1 - fc) + grid[:, rows0, cols1] * fc) * (1 - fr)
         + (grid[:, rows1, cols0] * (1 - fc) + grid[:, rows1, cols1] * fc) * fr) / 255

    # Composite deepest first, so shallower ice covers deeper ice.
    rgb = np.zeros((TILE_PX, TILE_PX, 3), np.float32)
    alpha = np.zeros((TILE_PX, TILE_PX), np.float32)
    for index in range(len(CLASSES) - 1, -1, -1):
        wi = w[index][..., None]
        rgb = _COLOURS[index] * wi + rgb * (1 - wi)
        alpha = w[index] + alpha * (1 - w[index])
    out = io.BytesIO()
    if not alpha.any():
        Image.new("RGBA", (TILE_PX, TILE_PX)).save(out, "PNG")
        return out.getvalue()
    rgb /= np.maximum(alpha, 1e-6)[..., None]
    rgb *= _hillshade(west, south, west + span, north, TILE_PX, TILE_PX)[..., None]
    rgba = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    Image.fromarray(rgba).save(out, "PNG")
    return out.getvalue()


def legend():
    """Class labels and colours for the viewer's legend."""
    return [{"label": label, "color": "#%02x%02x%02x" % rgb} for label, rgb, _ in CLASSES]
