"""Contour-line map tiles (transparent PNGs) drawn from the local elevation file.

The contour interval tightens as you zoom in; every 5th line is an index contour, drawn
bold and labelled with its elevation in metres.

The lines come in three styles (STYLES), so they stay readable over whatever is under
them. The viewer picks one from the layer that is showing (contourStyle in web/index.html):
  blue    over bare dark ground, with no imagery and no data layer on
  light   over the imagery and over data layers with dark colours
  dark    over data layers with light colours
"light" and "dark" lines carry a thin edge of the opposite tone, which keeps them visible
where the ground under them happens to match the line.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rasterio.enums import Resampling
from scipy import ndimage

import elevation
import tiles
from tiles import TILE_PX

MAX_LEVEL = 12  # 5 m/px on screen; the 200 m elevation data is smoothly upsampled here
INDEX_EVERY = 5
# Colours are copied from the tokens in web/theme.css (see DESIGN.md).
BLUE = (63, 182, 224)         # holographic blue
BRIGHT = (233, 251, 255)      # --holo-bright
DARK = (5, 11, 17)            # --holo-bg-solid
# style: line colour, opacity of thin lines (0-255), edge colour or None, edge opacity,
#        label colour, label edge colour.
# The bright edge of "dark" lines is kept faint: a stronger one outweighs the 1 px line
# between its two sides, and the line then reads as light.
STYLES = {
    "blue": (BLUE, 150, None, 0, BRIGHT, DARK),
    "light": (BRIGHT, 215, DARK, 130, BRIGHT, DARK),
    "dark": (DARK, 235, BRIGHT, 60, DARK, BRIGHT),
}
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


def tile_png(level, row, col, style="blue"):
    """One viewer tile of contour lines in one of STYLES, transparent between them."""
    line_rgb, line_alpha, edge_rgb, edge_alpha, label_rgb, label_edge = STYLES[style]
    west, south, east, north = tiles.bounds(level, row, col)
    px = (east - west) / TILE_PX
    # One extra pixel right and below so lines join across tile edges.
    z = elevation.read_elevation(
        west, max(south - px, -90), min(east + px, 180), north,
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
    rgba[..., :3] = line_rgb
    rgba[..., 3] = np.where(bold, 255, np.where(lines, line_alpha, 0))
    if edge_rgb:
        # One pixel of the opposite tone on each side of every line.
        drawn = lines | bold
        edge = ndimage.binary_dilation(drawn, structure=np.ones((3, 3), bool)) & ~drawn
        rgba[edge] = edge_rgb + (edge_alpha,)

    # Label up to two index contours, each at its pixel nearest the tile centre.
    # Labels stay inside a margin so they are never cut by a tile edge.
    ys, xs = np.nonzero(index[20:-20, 50:-50])
    if len(ys):
        ys, xs = ys + 20, xs + 50
        values = index_value[ys, xs]
        distance = (ys - TILE_PX / 2) ** 2 + (xs - TILE_PX / 2) ** 2
        image = Image.fromarray(rgba)
        draw = ImageDraw.Draw(image)
        for value in sorted(np.unique(values), key=lambda v: distance[values == v].min())[:2]:
            i = np.argmin(np.where(values == value, distance, np.inf))
            draw.text((xs[i], ys[i]), f"{int(value)}", font=LABEL_FONT, anchor="mm",
                      fill=label_rgb + (255,), stroke_width=2, stroke_fill=label_edge + (235,))
        rgba = np.array(image)
    return tiles.png(rgba)
