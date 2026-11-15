"""Serves the viewer (web/) and, from local data, each layer's map tiles, legend and values.

Run:  .venv/bin/uvicorn server:app --port 8000 --reload
"""
import gzip
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import contours
import elevation
import firmness
import temperature
import ice
import radiation
import routing
import tiles

app = FastAPI()

# Finished tiles are kept in memory, so a place that several visitors look at is drawn once.
# Each cache holds its layer's most recently used tiles; a tile is 1 to 400 KB, so all of
# them full come to about 300 MB. Every argument that changes the picture is part of the key.
TILES_KEPT = 200
# Terrain goes out as 16-bit integers (the heights are whole metres), gzip-compressed.
elevation_tile_bytes = lru_cache(TILES_KEPT)(
    lambda level, row, col: gzip.compress(elevation.tile(level, row, col).astype("<i2").tobytes(), 6))
contour_png = lru_cache(TILES_KEPT)(contours.tile_png)
firmness_png = lru_cache(TILES_KEPT)(firmness.tile_png)
temperature_png = lru_cache(TILES_KEPT)(temperature.tile_png)
ice_png = lru_cache(TILES_KEPT)(ice.tile_png)
radiation_png = lru_cache(2 * TILES_KEPT)(radiation.tile_png)        # two kinds of tile


# Tiles of the layers that never change (firmness, ice, radiation), drawn ahead of time by
# scripts/build_static_tiles.py into the same paths as their addresses. Optional.
TILES_DIR = Path(__file__).parent / "data/tiles"


def _saved(path):
    """The bytes of a tile drawn ahead of time, or None if it was not (then it is drawn now)."""
    file = TILES_DIR / path
    return file.read_bytes() if file.is_file() else None


def _png(data):
    return Response(data, media_type="image/png", headers=tiles.CACHE_HEADERS)


@app.get("/tiles-version.js")
def tiles_version():
    """Tells the page which version to put on tile addresses (see TILES_VERSION in tiles.py)."""
    return Response(f'window.TILES_VERSION = "{tiles.TILES_VERSION}";\n', media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


# ---- Terrain (elevation.py) and contour lines (contours.py) ----

@app.get("/elevation/{level}/{row}/{col}")
def elevation_tile(level: int, row: int, col: int):
    """257 x 257 heights in metres: little-endian int16, -32768 = no data, sent gzip-compressed."""
    return Response(elevation_tile_bytes(level, row, col), media_type="application/octet-stream",
                    headers={**tiles.CACHE_HEADERS, "Content-Encoding": "gzip"})


@app.get("/contours/{level}/{row}/{col}.png")
def contour_tile(level: int, row: int, col: int):
    return _png(contour_png(level, row, col))


# ---- Ground firmness (firmness.py) ----

@app.get("/firmness/{level}/{row}/{col}.png")
def firmness_tile(level: int, row: int, col: int):
    return _png(_saved(f"firmness/{level}/{row}/{col}.png") or firmness_png(level, row, col))


@app.get("/firmness/legend")
def firmness_legend():
    return firmness.legend()


# ---- Surface temperature (temperature.py) ----

def _stat(stat: str):
    return stat if stat in temperature.STATS else None        # anything else means "at local_time"


@app.get("/temperature/{level}/{row}/{col}.png")
def temperature_tile(level: int, row: int, col: int, ls: float = 0, local_time: float = 14, stat: str = "",
                     low: float | None = None, high: float | None = None):
    return _png(temperature_png(level, row, col, ls=ls, local_time=local_time, stat=_stat(stat), low=low, high=high))


@app.get("/temperature/range")
def temperature_range(west: float, south: float, east: float, north: float,
                      ls: float = 0, local_time: float = 14, stat: str = ""):
    """Colour range (kelvin) that shows the contrast inside one lon/lat box."""
    low, high = temperature.value_range(west, south, east, north, ls=ls, local_time=local_time, stat=_stat(stat))
    return {"low": low, "high": high}


@app.get("/temperature/point")
def temperature_point(lon: float, lat: float, ls: float = 0):
    """Ground properties and the 24-hour temperature cycle (kelvin) at one spot."""
    return temperature.diurnal_cycle(lon, lat, ls)


# ---- Water ice (ice.py) ----

@app.get("/ice/{level}/{row}/{col}.png")
def ice_tile(level: int, row: int, col: int):
    return _png(_saved(f"ice/{level}/{row}/{col}.png") or ice_png(level, row, col))


@app.get("/ice/legend")
def ice_legend():
    return ice.legend()


# ---- Radiation (radiation.py): modelled estimates anchored to Curiosity RAD ----

@app.get("/radiation/tiles/{kind}/{level}/{row}/{col}.png")
def radiation_tile(kind: str, level: int, row: int, col: int):
    if kind not in ("dose", "shelter"):
        raise HTTPException(404, "kind must be 'dose' or 'shelter'")
    return _png(_saved(f"radiation/tiles/{kind}/{level}/{row}/{col}.png") or radiation_png(kind, level, row, col))


@app.get("/radiation/point")
def radiation_point(lon: float, lat: float, multiplier: float = 1.0):
    """Safety-card radiation values for one place."""
    card = radiation.at_point(lon, lat, multiplier)
    if card is None:
        raise HTTPException(404, f"outside the Gale study area {radiation.GALE_BOX}")
    return card


class Route(BaseModel):
    points: List[List[float]]                  # [[lon, lat], ...]
    speed_kmh: float = 3.0
    stop_minutes: Optional[List[float]] = None  # minutes at each point
    multiplier: float = 1.0                    # "solar event" what-if scaling
    budget_msv: float = radiation.DEFAULT_EVA_BUDGET_MSV


@app.post("/radiation/route")
def radiation_route(route: Route):
    """Dose per leg and per stop along a walk, with a warning where the budget is crossed."""
    try:
        return radiation.route_dose(route.points, route.speed_kmh, route.stop_minutes,
                                    route.multiplier, route.budget_msv)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/radiation/shelters.geojson")
def radiation_shelters(count: int = 12):
    return radiation.shelters(count)


@app.get("/radiation/info")
def radiation_info():
    return radiation.info()


# ---- Routing (routing.py): the safest and the quickest trip between two points, by rover and on foot ----

@app.get("/routing/astronaut")
def routing_astronaut(from_lon: float, from_lat: float, to_lon: float, to_lat: float,
                      ls: float = 90, local_time: float = 12,
                      range_km: float = routing.ROVER_RANGE_KM, max_walk_km: float = routing.MAX_WALK_KM):
    try:
        return routing.plan((from_lon, from_lat), (to_lon, to_lat), ls=ls, local_time=local_time,
                            range_km=range_km, max_walk_km=max_walk_km)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/routing/legend")
def routing_legend():
    return routing.legend()


app.mount("/", StaticFiles(directory="web", html=True))
