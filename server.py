"""Serves the viewer (web/) plus terrain and contour-line tiles from the local elevation file.

Run:  .venv/bin/uvicorn server:app --port 8000
"""
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

import contours
import elevation

app = FastAPI()


@app.get("/elevation/{level}/{row}/{col}")
def elevation_tile(level: int, row: int, col: int):
    return Response(elevation.tile(level, row, col).tobytes(), media_type="application/octet-stream")


@app.get("/contours/{level}/{row}/{col}.png")
def contour_tile(level: int, row: int, col: int):
    return Response(contours.tile_png(level, row, col), media_type="image/png")


app.mount("/", StaticFiles(directory="web", html=True))
