# Interplanetary Survival Guide: an interactive map of Mars

NASA Space Apps Challenge project. A 3D, Google-Earth-style map of Mars with data layers
(elevation, slope, radiation, temperature and more), built to answer one question:
what is the safest route across the surface for astronauts and rovers?

## What works today

The base layer: the whole planet in 3D, modelled on the
[Murray Lab CTX viewer](https://murray-lab.caltech.edu/CTX/V01/SceneView/).

- Global CTX imagery at 5 m per pixel, draped over 200 m terrain
- Terrain read from our own copy of the NASA/USGS elevation data
- Two topography layers that can be shown together: colored elevation, and contour lines
  drawn from our elevation data (interval 2000 m zoomed out to 50 m zoomed in, bold lines labelled in metres)
- Ground firmness: thermal inertia at 3 km per pixel, coloured in six classes from loose dust
  (may not bear weight) to bedrock, with a legend
- Water ice: depth to the shallowest ice at 3 km per pixel, white for polar surface ice and
  light-to-dark blue for buried ice within 1 m, 1–5 m and deeper than 5 m, with a legend
- Rover traverses (Curiosity, Perseverance), IAU feature names, impact craters
- Coordinate readout, area measurement, elevation profile, layer list, bookmarks
- Python helpers to read elevation and compute slope for any area

The radiation layer (Gale crater): modelled dose rate and terrain shelter, anchored to the
Curiosity RAD measurement. See "Radiation layer" below.

Planned: more hazard layers on top of the base, then least-cost route finding across them.

## Setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Then download the elevation data (15 GB), the thermal inertia map (52 MB) and the water-ice
files (214 MB), none of them in git:
see [DATA_SOURCES.md](DATA_SOURCES.md).

## Run

```bash
.venv/bin/uvicorn server:app --port 8000
```

Open http://localhost:8000.

## Project layout

| Path | Role |
|---|---|
| `web/index.html` | The 3D viewer (ArcGIS Maps SDK for JS) |
| `web/data/` | Small vector layers shipped with the repo |
| `server.py` | Serves the viewer and the terrain, contour, firmness and ice tiles from local data |
| `elevation.py` | Reads elevation for a lon/lat box, computes slope, cuts terrain tiles |
| `radiation.py` | Radiation dose rate, terrain shelter, dose along a route, map tiles |
| `contours.py` | Draws contour-line map tiles from the elevation file |
| `firmness.py` | Reads thermal inertia for a lon/lat box, classifies ground firmness, draws its map tiles |
| `ice.py` | Combines polar surface ice and SWIM buried ice into depth classes, draws its map tiles |
| `data/` | Large downloaded datasets (gitignored) |
| `DATA_SOURCES.md` | Every dataset, download links, GIS conventions |

## Building on the base layer

All layers use plain lon/lat degrees on the Mars 2000 sphere (wkid 104971); details are in
[DATA_SOURCES.md](DATA_SOURCES.md).

**Elevation and slope in Python:**

```python
import elevation

# Gale crater, native 200 m resolution: (west, south, east, north)
box = (136.5, -6.0, 139.0, -4.0)
z = elevation.read_elevation(*box)                 # float32 metres, NaN = nodata
slope = elevation.slope_degrees(z, south=box[1], north=box[3], west=box[0], east=box[2])

# Whole planet on a coarse grid
world = elevation.read_elevation(-180, -90, 180, 90, shape=(2880, 5760))
```

**Ground firmness on the same grid:**

```python
import firmness

ti = firmness.read_thermal_inertia(*box, shape=z.shape)   # float32 tiu, NaN = nodata
soft = firmness.firmness_class(ti) == 0                   # loose dust, may not bear weight
```

Thermal inertia senses only the top few centimetres, averaged over 3 km, and is unreliable
poleward of about 60° (ice and seasonal frost).

**Water ice on the same grid:**

```python
import ice

depth = ice.read_ice_class(*box, shape=z.shape)   # int8: 0 surface, 1 within 1 m, 2 1–5 m, 3 deeper, -1 none
reachable = (depth == 0) | (depth == 1)           # ice on the surface or within 1 m
```

Buried ice is a SWIM consistency score of 0.3 or more, not a measured amount, and is mapped
only between 60°S and 60°N. Between 60° and the polar ice nothing is mapped.

To combine layers for routing, put each one on the same lon/lat box and array shape.

**Adding a layer to the viewer:** add it in `web/index.html` where the comment says
"Team layers go here". It appears in the layer list automatically. For vector data, save
GeoJSON with lon/lat in degrees into `web/data/`:

```js
map.add(new GeoJSONLayer({ url: "data/my-layer.geojson", title: "My layer" }));
```

## Radiation layer

Turn on "Radiation (Gale crater)" in the layer list. It has the dose rate overlay, the
fraction of sky blocked by terrain, the best natural shelters, and the Curiosity RAD
measurement. Click the map for the dose at that spot. It works without the 15 GB elevation
download: the Gale window is fetched once and cached.

Everything except the RAD marker is a modelled estimate; sources and assumptions are in
[DATA_SOURCES.md](DATA_SOURCES.md).

**For routing**, a dose-rate grid on any lon/lat box and shape (mSv per day):

```python
import radiation

box = (136.5, -6.0, 139.0, -4.0)                    # (west, south, east, north)
dose = radiation.dose_grid(*box, shape=(593, 741))  # NaN where there is no data
```

**For safety cards**, values at one stop, and dose along a walk:

```python
radiation.at_point(137.4417, -4.5895)
radiation.route_dose([[137.44, -4.59], [137.40, -4.65]], speed_kmh=3, stop_minutes=[0, 60])
```

The same over HTTP: `GET /radiation/point?lon=..&lat=..` and `POST /radiation/route` with
`{"points": [[lon, lat], ...], "speed_kmh": 3, "stop_minutes": [...], "multiplier": 1, "budget_msv": 0.3}`.
`multiplier` scales every dose rate for "what if a solar storm hits" scenarios; the response
lists a warning for the leg or stop where the budget is crossed.

## Credits

Imagery: NASA/JPL/MSSS/The Murray Lab. Topography: NASA GSFC, DLR, USGS Astrogeology, JPL, ESA.
Thermal inertia: NASA/MGS/TES, Putzig & Mellon (2007).
Water ice: SWIM project (Morgan & Putzig et al. 2025); polar ice units from USGS SIM 3292 (Tanaka et al. 2014).
