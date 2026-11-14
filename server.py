"""Serves the viewer (web/) plus terrain, contour-line and ground-firmness tiles from local data.

Run:  .venv/bin/uvicorn server:app --port 8000
"""
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

import contours
import elevation
import firmness

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


app.mount("/", StaticFiles(directory="web", html=True))
