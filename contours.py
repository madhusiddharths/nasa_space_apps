"""Contour-line map tiles (transparent PNGs) drawn from the local elevation file.

Same tiling scheme as the CTX imagery. The contour interval tightens as you zoom in;
every 5th line is an index contour, drawn bold and labelled with its elevation in metres.
"""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rasterio.enums import Resampling

import elevation

TILE_PX = 512
MAX_LEVEL = 12  # 5 m/px on screen; the 200 m elevation data is smoothly upsampled here
INDEX_EVERY = 5
LINE_RGB = (110, 55, 15)  # topo-map brown
LABEL_FONT = ImageFont.load_default(size=13)


def interval_m(level):
    """Vertical spacing between contour lines at a zoom level."""
    return [2000, 2000, 1000, 1000, 500, 500, 200, 200, 100, 100, 50, 50, 50][level]


def _crossings(z, step):
    """Pixels where the surface crosses a multiple of `step`, and the value crossed."""
    band = np.floor(z / step)
    right = band[:-1, 1:]
    below = band[1:, :-1]
    here = band[:-1, :-1]
    crossed = np.maximum(here, np.maximum(right, below)) * step
    return (here != right) | (here != below), crossed


def tile_png(level, row, col):
    span = 180 / 2**level
    px = span / TILE_PX
    west = -180 + col * span
    north = 90 - row * span
    # One extra pixel right and below so lines join across tile edges.
    z = elevation.read_elevation(
        west, max(north - span - px, -90), min(west + span + px, 180), north,
        shape=(TILE_PX + 1, TILE_PX + 1), resampling=Resampling.cubic,
    )
    step = interval_m(level)
    lines, _ = _crossings(z, step)
    index, index_value = _crossings(z, step * INDEX_EVERY)

    # Index contours are 2 px wide.
    bold = index.copy()
    bold[1:, :] |= index[:-1, :]
    bold[:, 1:] |= index[:, :-1]

    rgba = np.zeros((TILE_PX, TILE_PX, 4), np.uint8)
    rgba[..., :3] = LINE_RGB
    rgba[..., 3] = np.where(bold, 255, np.where(lines, 170, 0))
    image = Image.fromarray(rgba)

    # Label up to two index contours, each at its pixel nearest the tile centre.
    # Labels stay inside a margin so they are never cut by a tile edge.
    ys, xs = np.nonzero(index[20:-20, 50:-50])
    if len(ys):
        ys, xs = ys + 20, xs + 50
        values = index_value[ys, xs]
        distance = (ys - TILE_PX / 2) ** 2 + (xs - TILE_PX / 2) ** 2
        draw = ImageDraw.Draw(image)
        for value in sorted(np.unique(values), key=lambda v: distance[values == v].min())[:2]:
            i = np.argmin(np.where(values == value, distance, np.inf))
            draw.text((xs[i], ys[i]), f"{int(value)}", font=LABEL_FONT, anchor="mm",
                      fill=LINE_RGB + (255,), stroke_width=2, stroke_fill=(255, 255, 255, 230))

    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
