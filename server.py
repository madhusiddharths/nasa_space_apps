"""Serves the viewer (web/) and terrain tiles read from the local elevation file.

Run:  .venv/bin/uvicorn server:app --port 8000
"""
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

import elevation

app = FastAPI()


@app.get("/elevation/{level}/{row}/{col}")
def elevation_tile(level: int, row: int, col: int):
    return Response(elevation.tile(level, row, col).tobytes(), media_type="application/octet-stream")


app.mount("/", StaticFiles(directory="web", html=True))
