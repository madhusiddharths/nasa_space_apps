# Interplanetary Survival Guide: an interactive map of Mars

NASA Space Apps Challenge project. A 3D, Google-Earth-style map of Mars with hazard and
resource layers (terrain, ground firmness, water ice, radiation), built to answer one
question: what is the safest route across the surface for astronauts and rovers?

## What works today

**Base map**, modelled on the
[Murray Lab CTX viewer](https://murray-lab.caltech.edu/CTX/V01/SceneView/):

- Global CTX imagery at 5 m per pixel, draped over 200 m terrain
- Terrain read from our own copy of the NASA/USGS elevation data
- Two topography layers that can be shown together: colored elevation, and contour lines
  drawn from our elevation data (interval 2000 m zoomed out to 50 m zoomed in, bold lines labelled in metres)
- Ground firmness: thermal inertia at 3 km per pixel, coloured in six classes from loose dust
  (may not bear weight) to bedrock, with a legend
- Surface temperature for any season and time of day: a panel with season and local-time
  sliders, daily low / daily high / day-night swing, and a click readout with the 24-hour
  curve of that spot. Needs no download; 100 m detail where a THEMIS tile is downloaded
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

**Astronaut route planner.** Open "Astronaut route" (the directions button, top left), set a
start A and a destination B up to 100 km apart, and the map draws two walks:

- **Safest:** crosses as little hazardous ground as it can. If every possible route has to
  cross some hazard, that stretch is tagged *unavoidable* and drawn thick with a white edge.
- **Quickest:** the least walking time. It may cross Caution ground, but never Danger or
  Extreme ground unless that is unavoidable.

Each route lists distance, walking time, climb, steepest and coldest ground, radiation dose and
its hazards. Hazards come from slope (Caution from 10°, Danger from 20°, Extreme from 30°),
loose dust, and ground colder than −80 °C at the departure hour you choose.

Planned: rover routing, and round trips.

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
| `server.py` | Serves the viewer and the terrain, contour, firmness and temperature tiles from local data |
| `elevation.py` | Reads elevation for a lon/lat box, computes slope, cuts terrain tiles |
| `contours.py` | Draws contour-line map tiles from the elevation file |
| `firmness.py` | Reads thermal inertia for a lon/lat box, classifies ground firmness, draws its map tiles |
| `temperature.py` | Surface temperature for a lon/lat box, season and time of day; draws its map tiles |
| `temperature_data/` | Small maps and the lookup table `temperature.py` reads (in git, 16 MB) |
| `web/temperature.js` | The temperature panel and click readout in the viewer |
| `scripts/` | Rebuild `temperature_data/`, and check the temperature model against Curiosity |
| `server.py` | Serves the viewer and each layer's map tiles, legend and values |
| `tiles.py` | What every layer's tiles share: tiling scheme, tile size, PNG encoding |
| `elevation.py` | Reads elevation for a lon/lat box, computes slope, cuts terrain tiles |
| `contours.py` | Draws contour-line map tiles from the elevation file |
| `firmness.py` | Reads thermal inertia for a lon/lat box, classifies ground firmness, draws its map tiles |
| `ice.py` | Combines polar surface ice and SWIM buried ice into depth classes, draws its map tiles |
| `radiation.py` | Radiation dose rate, terrain shelter, dose along a route, map tiles |
| `routing.py` | Astronaut routing: hazard levels from the layers, safest and quickest walk from A to B |
| `web/routing.js` | The route planner panel and the route lines on the map |
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

**Surface temperature on the same grid:**

```python
import temperature

# Ls = season angle (90 = northern summer), local_time = local solar hour. Kelvin, no NaN.
t = temperature.read_temperature(*box, ls=90, local_time=14, shape=z.shape)
coldest = temperature.read_temperature(*box, ls=90, stat="min", shape=z.shape)   # also "max", "mean", "range"
spot = temperature.diurnal_cycle(137.44, -4.59, ls=90)    # 24 hourly values plus ground properties
```

It comes from a thermal model of the ground driven by THEMIS thermal inertia and TES albedo.
Checked against Curiosity's ground temperature sensor in Gale crater
(`scripts/validate_temperature.py`): nightly lows agree within about 3 K, afternoon highs
come out about 11 K too cold. It ignores slopes, shadows and dust storms, and poleward of
60° it assumes a typical ground (THEMIS thermal inertia stops there).

To combine layers for routing, put each one on the same lon/lat box and array shape.
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

## Routing

```python
import routing

result = routing.plan((137.38, -4.72), (137.47, -4.80), ls=90, local_time=12)   # [lon, lat] each
result["verdict"]                        # what no route can avoid, in words
safest = result["routes"]["safest"]      # also "quickest"
safest["line"], safest["minutes"], safest["hazards"]
```

The same over HTTP: `GET /routing/astronaut?from_lon=..&from_lat=..&to_lon=..&to_lat=..&ls=90&local_time=12`.

How it decides, in short (the full account is the docstring of `routing.py`):

- The area around A and B is cut into 200 m cells, each given a hazard level (Clear, Caution,
  Danger, Extreme) from slope, ground firmness and temperature.
- "Unavoidable" is proven, not guessed: if A and B are not connected through ground below some
  level, every route crosses that level.
- The safest route will walk up to 20 m further to stay off 1 m of Caution ground, and 400 m
  for Danger. The quickest minimises time: 3 km/h on flat firm ground, slower on slopes
  (Tobler's hiking function) and soft ground.

Every threshold, speed and penalty is a planning number chosen by the team, at the top of
`routing.py`; none is a NASA limit. Slopes are averages over 200 m, so short cliffs and boulders
are not seen, and "unavoidable" means within the searched area around A and B.

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
