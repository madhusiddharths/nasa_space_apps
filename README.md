# nasa_space_apps

Interactive 3D map of Mars for route planning. This is the base layer: the Murray Lab
CTX viewer (https://murray-lab.caltech.edu/CTX/V01/SceneView/) rebuilt locally, with the
3D terrain read from our own copy of the elevation data.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Download the elevation data (not in git) into `data/elevation/`: the 11 GB file and its
3.8 GB `.ovr` sidecar, which holds the low-resolution overviews. Without the sidecar,
zoomed-out reads take seconds instead of milliseconds.

```bash
mkdir -p data/elevation && cd data/elevation && curl -L -C - -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr
```

## Run

```bash
.venv/bin/uvicorn server:app --port 8000
```

Open http://localhost:8000.

## Where the data comes from

| Layer | Source | Local? |
|---|---|---|
| 3D terrain, HRSC+MOLA 200 m | `data/elevation/*.tif`, served by `server.py` at `/elevation/{level}/{row}/{col}` | yes |
| CTX mosaic, 5 m/px | `astro.arcgis.com/arcgis/rest/services/OnMars/CTX1/MapServer` | streamed |
| MOLA colored topography | `astro.arcgis.com/arcgis/rest/services/OnMars/MColorDEM/MapServer` | streamed |
| Impact craters | Esri `Mars_Nomenclature_Mountains` FeatureServer | streamed |
| CTX tile map (3,960 quads, links to downloads) | `web/data/MurrayLab_CTX_V01_Quad-Map.geojson` | yes |
| Curiosity traverse (to sol 3420) | `web/data/MSL_3420.geojson` | yes |
| Perseverance traverse (to sol 678) | `web/data/Mars2020_0678.geojson` | yes |
| IAU feature names | `web/data/mars-nomenclature.geojson` | yes |

The CTX imagery is streamed because the full mosaic is 5.6 TB.
Credit: NASA/JPL/MSSS/The Murray Lab; topography NASA GSFC, DLR, USGS Astrogeology, JPL.

## GIS reference (every layer must match this)

- **Coordinate system:** `GCS_Mars_2000_Sphere`, Esri wkid **104971**. Plain lon/lat in degrees.
- **Longitude:** -180 to 180, east positive. Convert 0–360°E data with `lon > 180 ? lon - 360 : lon`.
- **Latitude:** -90 to 90, planetocentric.
- **Sphere radius:** 3,396,190 m. 1° of latitude = 59,274.7 m. 1° of longitude = 59,274.7 × cos(lat) m.
- **Elevation file:** 106,694 × 53,347 px, 0.003374120830641°/px (200 m at the equator),
  int16 metres above the MOLA areoid, range -8,528 to 21,226, nodata -32768. Row 0 is north.

## Using elevation in Python

`elevation.py` reads any lon/lat box from the file and computes slope with true ground distances:

```python
import elevation

# Gale crater, native 200 m resolution: (west, south, east, north)
box = (136.5, -6.0, 139.0, -4.0)
z = elevation.read_elevation(*box)                 # float32 metres, NaN = nodata
slope = elevation.slope_degrees(z, south=box[1], north=box[3], west=box[0], east=box[2])

# Whole planet on a coarse grid (fast, uses the file's overviews)
world = elevation.read_elevation(-180, -90, 180, 90, shape=(2880, 5760))
```

To combine layers for routing, put each one on the same lon/lat box and array shape.

## Adding a layer to the viewer

Add it in `web/index.html` where the comment says "Team layers go here". It appears in the
layer list automatically.

**Vector data (points, lines, polygons):** save as GeoJSON with lon/lat in degrees, put it in `web/data/`:

```js
map.add(new GeoJSONLayer({ url: "data/my-layer.geojson", title: "My layer" }));
```

**Raster data (radiation, temperature, slope...):** simplest is one global PNG in
equirectangular projection covering -180..180, -90..90. Load `esri/layers/MediaLayer`,
`esri/layers/support/ImageElement` and `esri/layers/support/ExtentAndRotationGeoreference`
(this snippet is untested):

```js
map.add(new MediaLayer({
  title: "Radiation",
  opacity: 0.6,
  spatialReference: { wkid: 104971 },
  source: [new ImageElement({
    image: "data/radiation.png",
    georeference: new ExtentAndRotationGeoreference({
      extent: { xmin: -180, ymin: -90, xmax: 180, ymax: 90, spatialReference: { wkid: 104971 } },
    }),
  })],
}));
```

In the browser console, `marsView` and `marsMap` are exposed for debugging.
