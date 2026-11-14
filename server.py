"""Serves the viewer (web/) plus terrain, contour-line, ground-firmness and surface-temperature tiles from local data.

Run:  .venv/bin/uvicorn server:app --port 8000
"""
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

import contours
import elevation
import firmness
import temperature

app = FastAPI()


@app.get("/elevation/{level}/{row}/{col}")
def elevation_tile(level: int, row: int, col: int):
    return Response(elevation.tile(level, row, col).tobytes(), media_type="application/octet-stream")


@app.get("/contours/{level}/{row}/{col}.png")
def contour_tile(level: int, row: int, col: int):
    return Response(contours.tile_png(level, row, col), media_type="image/png")


@app.get("/firmness/{level}/{row}/{col}.png")
def firmness_tile(level: int, row: int, col: int):
    return Response(firmness.tile_png(level, row, col), media_type="image/png")


@app.get("/firmness/legend")
def firmness_legend():
    return firmness.legend()


def _stat(stat: str):
    return stat if stat in temperature.STATS else None        # anything else means "at local_time"


@app.get("/temperature/{level}/{row}/{col}.png")
def temperature_tile(level: int, row: int, col: int, ls: float = 0, local_time: float = 14, stat: str = "",
                     low: float | None = None, high: float | None = None):
    png = temperature.tile_png(level, row, col, ls=ls, local_time=local_time, stat=_stat(stat), low=low, high=high)
    return Response(png, media_type="image/png")


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


app.mount("/", StaticFiles(directory="web", html=True))
