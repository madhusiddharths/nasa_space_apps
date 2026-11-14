# Data sources

Where every dataset comes from, what you have to download after cloning, and the GIS
conventions all layers share.

## Download after cloning

The `data/` folder is not in git. Create it inside the cloned repo and download:

| Dataset | Size | Goes in | Link |
|---|---|---|---|
| Mars HRSC + MOLA blended elevation, 200 m, v2 (USGS) | 11.4 GB | `data/elevation/` | [Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) |
| Its overview sidecar (low-resolution copies) | 3.8 GB | `data/elevation/` | [Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr) |

Both files are required and must keep these names. Without the `.ovr` file, zoomed-out
reads take seconds instead of milliseconds.

One command from the repo root (resumes if interrupted):

```bash
mkdir -p data/elevation && cd data/elevation && curl -L -C - -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr
```

Dataset page: https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m

Expected layout:

```
data/
  elevation/
    Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif
    Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr
```

## Already in the repo (`web/data/`)

Copied from the Murray Lab CTX viewer. No download needed.

| File | What it is | Source |
|---|---|---|
| `MSL_3420.geojson` | Curiosity traverse, to sol 3420 | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/MSL_3420.geojson), NASA/JPL/MSL |
| `Mars2020_0678.geojson` | Perseverance traverse, to sol 678 | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/Mars2020_0678.geojson), NASA/JPL/M2020 |
| `mars-nomenclature.geojson` | IAU feature names | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/mars-nomenclature.geojson), IAU WGPSN |
| `MurrayLab_CTX_V01_Quad-Map.geojson` | The 3,960 CTX mosaic tiles (4°×4°), each with a link to its download page | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/MurrayLab_CTX_V01_Quad-Map.geojson) |

## Streamed at runtime (needs internet)

| Layer | Service |
|---|---|
| CTX global mosaic, 5 m/px | `https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX1/MapServer` |
| MOLA colored topography | `https://astro.arcgis.com/arcgis/rest/services/OnMars/MColorDEM/MapServer` |
| Impact craters | `https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/Mars_Nomenclature_Mountains/FeatureServer` |
| Map software (ArcGIS Maps SDK for JS 4.26) | `https://js.arcgis.com/4.26/` |

The CTX imagery is streamed because the full mosaic is 5.6 TB. Full-resolution 4°×4°
tiles can be downloaded one at a time from https://murray-lab.caltech.edu/CTX/ ("Access the Data").

## Credits

- CTX mosaic: NASA/JPL/MSSS/The Murray Lab
- Elevation: NASA GSFC, DLR, USGS Astrogeology, JPL, ESA (HRSC + MOLA blend)
- Feature names: IAU Working Group for Planetary System Nomenclature

## GIS reference (every layer must match this)

- **Coordinate system:** `GCS_Mars_2000_Sphere`, Esri wkid **104971**. Plain lon/lat in degrees.
- **Longitude:** -180 to 180, east positive. Convert 0–360°E data with `lon > 180 ? lon - 360 : lon`.
- **Latitude:** -90 to 90, planetocentric.
- **Sphere radius:** 3,396,190 m. 1° of latitude = 59,274.7 m. 1° of longitude = 59,274.7 × cos(lat) m.
- **Elevation file:** 106,694 × 53,347 px, 0.003374120830641°/px (200 m at the equator),
  int16 metres above the MOLA areoid, range -8,528 to 21,226, nodata -32768. Row 0 is north.
