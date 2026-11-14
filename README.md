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
- Surface temperature for any season and time of day: a panel with season and local-time
  sliders, daily low / daily high / day-night swing, and a click readout with the 24-hour
  curve of that spot. Needs no download; 100 m detail where a THEMIS tile is downloaded
- Rover traverses (Curiosity, Perseverance), IAU feature names, impact craters
- Coordinate readout, area measurement, elevation profile, layer list, bookmarks
- Python helpers to read elevation and compute slope for any area

Planned: hazard layers on top of the base, then least-cost route finding across them.

## Setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Then download the elevation data (15 GB) and the thermal inertia map (52 MB), neither in git:
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
| `server.py` | Serves the viewer and the terrain, contour, firmness and temperature tiles from local data |
| `elevation.py` | Reads elevation for a lon/lat box, computes slope, cuts terrain tiles |
| `contours.py` | Draws contour-line map tiles from the elevation file |
| `firmness.py` | Reads thermal inertia for a lon/lat box, classifies ground firmness, draws its map tiles |
| `temperature.py` | Surface temperature for a lon/lat box, season and time of day; draws its map tiles |
| `temperature_data/` | Small maps and the lookup table `temperature.py` reads (in git, 16 MB) |
| `web/temperature.js` | The temperature panel and click readout in the viewer |
| `scripts/` | Rebuild `temperature_data/`, and check the temperature model against Curiosity |
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

**Adding a layer to the viewer:** add it in `web/index.html` where the comment says
"Team layers go here". It appears in the layer list automatically. For vector data, save
GeoJSON with lon/lat in degrees into `web/data/`:

```js
map.add(new GeoJSONLayer({ url: "data/my-layer.geojson", title: "My layer" }));
```

## Credits

Imagery: NASA/JPL/MSSS/The Murray Lab. Topography: NASA GSFC, DLR, USGS Astrogeology, JPL, ESA.
Thermal inertia: NASA/MGS/TES, Putzig & Mellon (2007).
