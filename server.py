"""Serves the viewer (web/) and terrain tiles read from the local elevation file.

Run:  .venv/bin/uvicorn server:app --port 8000
"""
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import elevation
import radiation

app = FastAPI()


@app.get("/elevation/{level}/{row}/{col}")
def elevation_tile(level: int, row: int, col: int):
    return Response(elevation.tile(level, row, col).tobytes(), media_type="application/octet-stream")


# ---- Radiation layer (radiation.py). Values are modelled estimates anchored to Curiosity RAD. ----

@app.get("/radiation/tiles/{kind}/{level}/{row}/{col}.png")
def radiation_tile(kind: str, level: int, row: int, col: int):
    if kind not in ("dose", "shelter"):
        raise HTTPException(404, "kind must be 'dose' or 'shelter'")
    return Response(radiation.tile_png(kind, level, row, col), media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


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


app.mount("/", StaticFiles(directory="web", html=True))
