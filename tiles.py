"""What every layer's map tiles share: the tiling scheme, the tile size and PNG encoding.

The scheme is the CTX imagery's: origin (-180, 90), level 0 is two 180-degree tiles side
by side, and each level halves the tile span. web/index.html declares the same scheme in
marsTileInfo().
"""
import io

import numpy as np
from PIL import Image

TILE_PX = 512


def bounds(level, row, col):
    """(west, south, east, north) of one tile, in degrees."""
    span = 180 / 2**level
    west = -180 + col * span
    north = 90 - row * span
    return west, north - span, west + span, north


def cell_centres(west, south, east, north, rows, cols):
    """Latitude of each row and longitude of each column, at the cell centres of a
    rows x cols grid over a lon/lat box (a tile or any other box). Row 0 is north."""
    lats = north - (np.arange(rows) + 0.5) * (north - south) / rows
    lons = west + (np.arange(cols) + 0.5) * (east - west) / cols
    return lats, lons


def png(rgba):
    """PNG bytes for a (rows, cols, 4) uint8 RGBA array."""
    out = io.BytesIO()
    Image.fromarray(rgba).save(out, "PNG")
    return out.getvalue()


def hex_color(rgb):
    """'#rrggbb' for an (r, g, b) tuple, as the viewer's legends expect."""
    return "#%02x%02x%02x" % tuple(rgb)
