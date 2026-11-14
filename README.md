# Interplanetary Survival Guide: an interactive map of Mars

NASA Space Apps Challenge project. A 3D, Google-Earth-style map of Mars with hazard and
resource layers (terrain, ground firmness, water ice, radiation), built to answer one
question: what is the safest route across the surface for astronauts and rovers?

## What works today

**Base map**, modelled on the
[Murray Lab CTX viewer](https://murray-lab.caltech.edu/CTX/V01/SceneView/):

- Global CTX imagery at 5 m per pixel, draped over 200 m terrain read from our own copy of
  the NASA/USGS elevation data
- Rover traverses (Curiosity, Perseverance), IAU feature names, impact craters
- Coordinate readout, area measurement, elevation profile, layer list, bookmarks

**Layers**, each switched on from the layer list (firmness, ice and radiation show a legend):

| Layer | What it shows | Coverage |
|---|---|---|
| Topography | Colored elevation, and contour lines drawn from our elevation data (interval 2000 m zoomed out to 50 m zoomed in, bold lines labelled in metres) | Global |
| Ground firmness | Thermal inertia in six classes, from loose dust that may not bear weight to bedrock | Global, 3 km per pixel |
| Water ice | Depth to the shallowest ice: white for polar surface ice, light-to-dark blue for buried ice within 1 m, 1–5 m and deeper than 5 m | Global, 3 km per pixel; buried ice 60°S to 60°N only |
| Radiation | Modelled dose rate, sky blocked by terrain, the best natural shelters, and the Curiosity RAD measurement. Click the map for the dose at that spot | Gale crater |

Every layer can also be read in Python on a shared grid; see "Using the layers in Python".

Planned: least-cost route finding across the layers.

## Setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

On Windows, use `python` instead of `python3` and `.venv/Scripts/` instead of `.venv/bin/`.

Then download the data, none of which is in git: elevation (15 GB), thermal inertia (52 MB)
and water ice (214 MB). Commands are in [DATA_SOURCES.md](DATA_SOURCES.md). The radiation
layer needs no download of its own.

## Run

```bash
.venv/bin/uvicorn server:app --port 8000 --reload
```

Open http://localhost:8000. With `--reload` the server restarts when a Python file changes;
changes under `web/` only need a browser refresh.

## Project layout

| Path | Role |
|---|---|
| `web/index.html` | The 3D viewer (ArcGIS Maps SDK for JS) |
| `web/data/` | Small vector layers shipped with the repo |
| `server.py` | Serves the viewer and each layer's map tiles, legend and values |
| `tiles.py` | What every layer's tiles share: tiling scheme, tile size, PNG encoding |
| `elevation.py` | Reads elevation for a lon/lat box, computes slope, cuts terrain tiles |
| `contours.py` | Draws contour-line map tiles from the elevation file |
| `firmness.py` | Reads thermal inertia for a lon/lat box, classifies ground firmness, draws its map tiles |
| `ice.py` | Combines polar surface ice and SWIM buried ice into depth classes, draws its map tiles |
| `radiation.py` | Radiation dose rate, terrain shelter, dose along a route, map tiles |
| `data/` | Large downloaded datasets (gitignored) |
| `DATA_SOURCES.md` | Every dataset, download links, model assumptions, GIS conventions |

## Using the layers in Python

All layers use plain lon/lat degrees on the Mars 2000 sphere (wkid 104971); details are in
[DATA_SOURCES.md](DATA_SOURCES.md). To combine layers for routing, read each one on the same
lon/lat box and array shape.

**Elevation and slope:**

```python
import elevation

# Gale crater, native 200 m resolution: (west, south, east, north)
box = (136.5, -6.0, 139.0, -4.0)
z = elevation.read_elevation(*box)                 # float32 metres, NaN = nodata
slope = elevation.slope_degrees(z, south=box[1], north=box[3], west=box[0], east=box[2])

# Whole planet on a coarse grid
world = elevation.read_elevation(-180, -90, 180, 90, shape=(2880, 5760))
```

**Ground firmness:**

```python
import firmness

ti = firmness.read_thermal_inertia(*box, shape=z.shape)   # float32 tiu, NaN = nodata
soft = firmness.firmness_class(ti) == 0                   # loose dust, may not bear weight
```

Thermal inertia senses only the top few centimetres, averaged over 3 km, and is unreliable
poleward of about 60° (ice and seasonal frost).

**Water ice:**

```python
import ice

depth = ice.read_ice_class(*box, shape=z.shape)   # int8: 0 surface, 1 within 1 m, 2 1–5 m, 3 deeper, -1 none
reachable = (depth == 0) | (depth == 1)           # ice on the surface or within 1 m
```

Buried ice is a SWIM consistency score of 0.3 or more, not a measured amount, and is mapped
only between 60°S and 60°N. Between 60° and the polar ice nothing is mapped. The classes come
from the same smoothed data as the map: every source ice pixel is included, and smoothing adds
2–11% more area per depth by filling small gaps.

**Radiation:**

```python
import radiation

dose = radiation.dose_grid(*box, shape=z.shape)   # mSv per day, NaN where there is no data

# Values at one stop, and dose along a walk
radiation.at_point(137.4417, -4.5895)
radiation.route_dose([[137.44, -4.59], [137.40, -4.65]], speed_kmh=3, stop_minutes=[0, 60])
```

Everything except the RAD marker is a modelled estimate; sources and assumptions are in
[DATA_SOURCES.md](DATA_SOURCES.md). Terrain shelter is modelled inside Gale crater only. The
layer works without the 15 GB elevation download: the Gale window is fetched once and cached.

The same over HTTP: `GET /radiation/point?lon=..&lat=..` and `POST /radiation/route` with
`{"points": [[lon, lat], ...], "speed_kmh": 3, "stop_minutes": [...], "multiplier": 1, "budget_msv": 0.3}`.
`multiplier` scales every dose rate for "what if a solar storm hits" scenarios; the response
lists a warning for the leg or stop where the budget is crossed.

## Adding a layer

1. **Python module** (for raster data): a `read_...(west, south, east, north, shape=None)`
   function like the ones above, and a `tile_png(level, row, col)` that draws one map tile
   using `tiles.bounds()` and `tiles.png()`. `firmness.py` is the shortest example.
2. **`server.py`:** a `/<name>/{level}/{row}/{col}.png` endpoint that returns the tile.
3. **`web/index.html`:** create the layer where the comment says "New layers go here". It
   appears in the layer list automatically.

```js
const myLayer = serverTiles("my-layer", 8, { title: "My layer", opacity: 0.6 });
```

For vector data, skip steps 1 and 2: save GeoJSON with lon/lat in degrees into `web/data/`
and use `new GeoJSONLayer({ url: "data/my-layer.geojson", title: "My layer" })`.

## Credits

Imagery: NASA/JPL/MSSS/The Murray Lab. Topography: NASA GSFC, DLR, USGS Astrogeology, JPL, ESA.
Thermal inertia: NASA/MGS/TES, Putzig & Mellon (2007).
Water ice: SWIM project (Morgan & Putzig et al. 2025); polar ice units from USGS SIM 3292 (Tanaka et al. 2014).
Radiation: NASA/JPL-Caltech/SwRI (MSL RAD), NASA/JPL/JSC (Odyssey MARIE).
