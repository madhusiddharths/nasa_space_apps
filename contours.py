"""Contour-line map tiles drawn from the local elevation file.

The contour interval tightens as you zoom in; every 5th line is an index contour, drawn
bold and labelled with its elevation in metres.

A tile carries no colours. It is a mask that says, for each pixel, how much of it is line,
line edge, label text and label edge. The viewer colours it (CONTOUR_STYLES and
colourContours in web/index.html) in one of three styles, so the lines stay readable over
whatever is under them, and can switch style without asking the server again.

The mask is an opaque RGB picture, one mask per colour channel:
  red     label edge: how much of the pixel the 2 px outline around a label covers, 0-255
  green   label text: how much of the pixel the label's digits cover, 0-255
  blue    line: LINE_BOLD on an index contour, LINE_THIN on any other contour, LINE_EDGE on
          the one pixel either side of a line, 0 elsewhere
It is opaque because browsers multiply a pixel's colour by its transparency when they
decode a picture, which would wipe the masks wherever the pixel is see-through.
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
LINE_BOLD, LINE_THIN, LINE_EDGE = 255, 128, 64   # values of the blue channel; colourContours reads them
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
    """One viewer tile of contour lines, as the mask described at the top of this file."""
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

    # One pixel of edge on each side of every line.
    drawn = lines | bold
    edge = ndimage.binary_dilation(drawn, structure=np.ones((3, 3), bool)) & ~drawn
    mask = np.zeros((TILE_PX, TILE_PX, 3), np.uint8)
    mask[..., 2] = np.where(bold, LINE_BOLD, np.where(lines, LINE_THIN, np.where(edge, LINE_EDGE, 0)))

    # Label up to two index contours, each at its pixel nearest the tile centre.
    # Labels stay inside a margin so they are never cut by a tile edge.
    ys, xs = np.nonzero(index[20:-20, 50:-50])
    if len(ys):
        ys, xs = ys + 20, xs + 50
        values = index_value[ys, xs]
        distance = (ys - TILE_PX / 2) ** 2 + (xs - TILE_PX / 2) ** 2
        # Drawn in red (the outline) then red + green (the digits), which leaves the outline's
        # cover in the red channel and the digits' cover in the green one.
        image = Image.new("RGB", (TILE_PX, TILE_PX))
        draw = ImageDraw.Draw(image)
        for value in sorted(np.unique(values), key=lambda v: distance[values == v].min())[:2]:
            i = np.argmin(np.where(values == value, distance, np.inf))
            draw.text((xs[i], ys[i]), f"{int(value)}", font=LABEL_FONT, anchor="mm",
                      fill=(255, 255, 0), stroke_width=2, stroke_fill=(255, 0, 0))
        mask[..., :2] = np.array(image)[..., :2]
    return tiles.png(mask)
