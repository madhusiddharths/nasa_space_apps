"""Builds the water-ice grid ice.py reads (already committed in ice_data/):

  mars_ice_weights_20ppd.tif   four bands, one per depth class of ice.CLASSES, 0.05 deg/px.
                               Each value is 0..255 for a weight 0..1 that ice of that class
                               is present (128 = SWIM score 0.3, the ice cut-off).

You only need to run this to rebuild it, after downloading the SWIM maps and the polar ice
outlines into data/water_ice/ (commands in DATA_SOURCES.md). It takes about a minute.

Why a prebuilt file: the smoothing below works on three whole-planet maps at once. Doing
it inside the server made the first ice tile take about a minute and held 100 MB in
memory. The file is compressed, tiled and carries reduced copies of itself, so ice.py
reads only the window a tile needs, like elevation.py and firmness.py do.

How the grid is made (the same steps ice.py's docstring describes):
  Buried ice   The SWIM scores are smoothed over about 24 km (Gaussian, sigma 8 px), which
               rounds the square footprints of SWIM's coarser inputs, then turned into a
               weight that fades in around the cut-off. Every ice pixel the smoothing would
               drop (small patches, thin streaks, corners) is added back at its own size
               with a soft edge, so no ice in the source maps is left out.
  Surface ice  The polar ice outlines, with a soft edge.

Run:  .venv/bin/python scripts/build_ice_grid.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import ice  # noqa: E402  (the classes, the grid size and where the file goes)

SOURCE = ROOT / "data/water_ice"
SMOOTH_PX = 8      # Gaussian sigma for the SWIM scores, in 3 km pixels
EDGE_SCORE = 0.1   # score range over which a class fades in, centred on ice.ICE_SCORE
OVERVIEWS = [2, 4, 8, 16]


def blur(a, sigma):
    """Gaussian blur; wraps in longitude, repeats the edge rows in latitude."""
    r = int(3 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(a, ((r, r), (0, 0)), mode="edge")
    a = sum(w * padded[i:i + a.shape[0]] for i, w in enumerate(kernel))
    padded = np.pad(a, ((0, 0), (r, r)), mode="wrap")
    return sum(w * padded[:, i:i + a.shape[1]] for i, w in enumerate(kernel))


def build():
    """Per-class ice-presence weights for the whole planet: (class, rows, cols) uint8."""
    weights = np.zeros((len(ice.CLASSES), ice.ROWS, ice.COLS), np.uint8)
    swim_rows = slice(int(30 / ice.DEG_PER_PX), int(150 / ice.DEG_PER_PX))  # 60N..60S
    for index in range(1, len(ice.CLASSES)):
        with rasterio.open(SOURCE / ice.CLASSES[index][2]) as src:
            score = src.read(1)
        ramp = np.clip((blur(score, SMOOTH_PX) - ice.ICE_SCORE) / EDGE_SCORE + 0.5, 0, 1)
        # Ice the smoothing lost, kept at its own size: a slight blur for a soft edge,
        # doubled so that even a single 3 km pixel still counts as ice.
        dropped = (score >= ice.ICE_SCORE) & (ramp < 0.5)
        detail = np.clip(blur(dropped.astype(np.float32), 0.7) * 2, 0, 1)
        weights[index, swim_rows] = np.round(np.maximum(ramp, detail) * 255)
    polar = json.loads((SOURCE / "polar_surface_ice.geojson").read_text())
    surface = rasterize(
        [feature["geometry"] for feature in polar["features"]],
        out_shape=(ice.ROWS, ice.COLS),
        transform=from_origin(-180, 90, ice.DEG_PER_PX, ice.DEG_PER_PX),
    )
    # Soft edge, but never below 0.5 inside the mapped units, so thin slivers stay.
    surface = surface.astype(np.float32)
    weights[0] = np.round(np.maximum(blur(surface, 1), surface * 0.5) * 255)
    return weights


def main():
    weights = build()
    ice.GRID_PATH.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        ice.GRID_PATH, "w", driver="GTiff", count=len(ice.CLASSES), dtype="uint8",
        height=ice.ROWS, width=ice.COLS,
        transform=from_origin(-180, 90, ice.DEG_PER_PX, ice.DEG_PER_PX),
        tiled=True, blockxsize=512, blockysize=512, compress="deflate", predictor=2,
        # Four plain data bands. Without these two, a 4-band byte file is taken for
        # red, green, blue and transparency, and band 4 would blank out the other three.
        photometric="MINISBLACK", alpha="NO",
    ) as dst:
        dst.write(weights)
        dst.build_overviews(OVERVIEWS, Resampling.average)
        for index, (label, _, _) in enumerate(ice.CLASSES, start=1):
            dst.set_band_description(index, label)
    print(f"wrote {ice.GRID_PATH} ({ice.GRID_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
