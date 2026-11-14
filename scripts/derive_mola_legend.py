"""Works out the colour scale of the streamed "MOLA Topography" layer, for its legend.

The layer is Esri's colourised, relief-shaded picture of the same 200 m elevation model
we hold locally (service OnMars/MColorDEM). The service publishes no legend, so this
reads the colours back off the map: it downloads the whole planet at a coarse zoom,
pairs every pixel with the elevation at that spot from our file, keeps the nearly flat
ground (where the relief shading leaves the colour alone), and takes the typical colour
in each elevation band.

The result is printed as the MOLA_RAMP list that web/index.html holds. It is a reading
of the picture, not the service's own table, so the legend calls it approximate.

Run:  .venv/bin/python scripts/derive_mola_legend.py
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import elevation  # noqa: E402

SERVICE = "https://astro.arcgis.com/arcgis/rest/services/OnMars/MColorDEM/MapServer"
LEVEL = 2                 # whole planet in 8 x 4 tiles
BAND_M = 1000             # one legend stop per kilometre of elevation
FLAT_DEG = 1.0            # ground flatter than this counts as unshaded
MIN_PIXELS = 200          # bands with fewer flat pixels are left out


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "mars-viewer-legend"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    info = json.loads(fetch(SERVICE + "?f=json"))["tileInfo"]
    size = info["rows"]
    cols, rows = 2 * 2**LEVEL, 2**LEVEL
    picture = np.zeros((rows * size, cols * size, 3), np.uint8)
    for row in range(rows):
        for col in range(cols):
            tile = Image.open(io.BytesIO(fetch(f"{SERVICE}/tile/{LEVEL}/{row}/{col}"))).convert("RGB")
            picture[row * size:(row + 1) * size, col * size:(col + 1) * size] = np.array(tile)

    z = elevation.read_elevation(-180, -90, 180, 90, shape=picture.shape[:2])
    slope = elevation.slope_degrees(z, south=-90, north=90, west=-180, east=180)
    flat = (slope < FLAT_DEG) & ~np.isnan(z)
    flat[: picture.shape[0] // 18] = flat[-(picture.shape[0] // 18):] = False   # skip the poles (stretched pixels)

    band = np.floor(z / BAND_M)
    ramp = []
    for b in range(int(np.nanmin(band)), int(np.nanmax(band)) + 1):
        chosen = flat & (band == b)
        if chosen.sum() >= MIN_PIXELS:
            r, g, bl = np.median(picture[chosen], axis=0).astype(int)
            ramp.append([int((b + 0.5) * BAND_M), "#%02x%02x%02x" % (r, g, bl)])
    print(f"// {len(ramp)} stops from {int(flat.sum())} flat pixels, tile size {size}")
    print("const MOLA_RAMP = " + json.dumps(ramp) + ";")


if __name__ == "__main__":
    main()
