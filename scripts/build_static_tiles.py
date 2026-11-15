"""Draws, ahead of time, every tile of the layers whose picture never changes.

Ground firmness, water ice and radiation (dose rate and sky blocked) always draw the same
tile for the same place, so they can be drawn once and kept as files. server.py sends the
saved file when there is one and draws the tile as before when there is not.

The files go in data/tiles/ (not in git), laid out exactly as the tile addresses are:
    data/tiles/firmness/<level>/<row>/<col>.png
    data/tiles/ice/<level>/<row>/<col>.png
    data/tiles/radiation/tiles/dose/<level>/<row>/<col>.png
    data/tiles/radiation/tiles/shelter/<level>/<row>/<col>.png
so the folder can later be copied to a file host or CDN and served with no Python at all.

Tiles with nothing on them (fully transparent) are not saved. Without the full elevation
file the radiation layers cover Gale crater only, and only those tiles are saved.

With the full elevation file, all four layers come to about 121,000 tiles and 9 GB (ice 6.9 GB,
dose 2.2 GB, firmness 0.3 GB), drawn in about 10 minutes on an 11-core laptop.

Run:  python scripts/build_static_tiles.py            all four layers
      python scripts/build_static_tiles.py ice        one layer (firmness, ice, dose, shelter)
Run it again after changing how a layer is drawn (and raise TILES_VERSION in tiles.py).
"""
import io
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
import firmness
import ice
import radiation
import server

# name -> (folder under data/tiles = the tile address, zoom levels, function that draws a tile).
# The levels are the ones web/index.html declares for the layer (serverTiles(path, levels, ...)).
LAYERS = {
    "firmness": ("firmness", 8, firmness.tile_png),
    "ice": ("ice", 8, ice.tile_png),
    "dose": ("radiation/tiles/dose", 8, lambda level, row, col: radiation.tile_png("dose", level, row, col)),
    "shelter": ("radiation/tiles/shelter", 8, lambda level, row, col: radiation.tile_png("shelter", level, row, col)),
}


def draw(job):
    """Draws one tile and saves it unless it is empty. Returns the bytes saved (0 if empty)."""
    name, level, row, col = job
    folder, _, tile_png = LAYERS[name]
    png = tile_png(level, row, col)
    image = Image.open(io.BytesIO(png))
    if image.mode == "RGBA" and image.getextrema()[3][1] == 0:
        return 0
    path = server.TILES_DIR / folder / str(level) / str(row) / f"{col}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return len(png)


if __name__ == "__main__":
    for name in sys.argv[1:] or LAYERS:
        folder, levels, _ = LAYERS[name]
        shutil.rmtree(server.TILES_DIR / folder, ignore_errors=True)      # no stale tiles from an earlier run
        jobs = [(name, level, row, col) for level in range(levels)
                for row in range(2**level) for col in range(2 * 2**level)]
        start = time.time()
        with ProcessPoolExecutor() as pool:
            sizes = list(pool.map(draw, jobs, chunksize=64))
        saved = [s for s in sizes if s]
        print(f"{name}: {len(saved)} tiles saved of {len(jobs)} (levels 0-{levels - 1}), "
              f"{sum(saved) / 1e6:.0f} MB, {time.time() - start:.0f} s")
