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

## Radiation layer

No download needed for Gale crater. If the 15 GB elevation file above is missing,
`radiation.py` fetches only the Gale window (136.5 to 139.0°E, 6.0 to 4.0°S) from the same
USGS file on first use (about 30 s) and caches it in `data/radiation/`.

Every radiation value shown is a **modelled estimate** except the RAD marker, which is a
**measurement**.

| Source | Kind | What we take from it | Link |
|---|---|---|---|
| Curiosity RAD, surface dose at Gale (Hassler et al. 2014, *Science* 343, 1244797) | Measured | The anchor: 0.210 ± 0.040 mGy/day absorbed dose, 0.64 ± 0.12 mSv/day dose equivalent, Aug 2012 to Jun 2013 | [doi:10.1126/science.1244797](https://doi.org/10.1126/science.1244797) |
| Curiosity RAD beside butte M12, sols 1456 to 1467 (Ehresmann et al. 2021, *JGR Planets* 126, e2021JE006851) | Measured | Shelter strength: 19% of the sky blocked lowered the dose rate by 4% | [doi:10.1029/2021JE006851](https://doi.org/10.1029/2021JE006851) |
| Odyssey MARIE + MOLA estimated dose map (NASA/JPL PIA03480) | Modelled by NASA | How much dose changes with elevation: 10 rem/yr on the lowest ground to 20 rem/yr on the highest | [PIA03480](https://www.jpl.nasa.gov/images/pia03480-estimated-radiation-dosage-on-mars/) |
| HRSC + MOLA elevation (above) | Measured | Elevation, and the horizon scan for terrain shelter | see "Download after cloning" |

Model assumptions (all in `radiation.py`, also served at `/radiation/info`): 610 Pa mean
pressure at 0 m, 11.1 km atmospheric scale height, 3.71 m/s² gravity, exponential
attenuation of dose with atmospheric column (47.6 g/cm², fitted to the PIA03480 range),
horizon scanned in 16 directions out to 20 km on 200 m terrain. The 0.3 mSv excursion
budget is a team planning number, not a NASA limit; the 600 mSv career limit is from
NASA-STD-3001.

Limits: no solar particle events or solar-cycle changes, no dust or seasonal pressure
changes, and cliffs or buttes smaller than 200 m are not seen, so real shelter can be
better than shown.

## Already in the repo (`web/data/`)

Copied from the Murray Lab CTX viewer. No download needed.

| File | What it is | Source |
|---|---|---|
| `MSL_3420.geojson` | Curiosity traverse, to sol 3420 | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/MSL_3420.geojson), NASA/JPL/MSL |
| `Mars2020_0678.geojson` | Perseverance traverse, to sol 678 | [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/Features/Mars2020_0678.geojson), NASA/JPL/M2020 |
| `rad-measurement.geojson` | The Curiosity RAD surface dose measurement, as a map point | Hassler et al. 2014, NASA/JPL-Caltech/SwRI |
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
- Radiation: NASA/JPL-Caltech/SwRI (MSL RAD), NASA/JPL/JSC (Odyssey MARIE)

## GIS reference (every layer must match this)

- **Coordinate system:** `GCS_Mars_2000_Sphere`, Esri wkid **104971**. Plain lon/lat in degrees.
- **Longitude:** -180 to 180, east positive. Convert 0–360°E data with `lon > 180 ? lon - 360 : lon`.
- **Latitude:** -90 to 90, planetocentric.
- **Sphere radius:** 3,396,190 m. 1° of latitude = 59,274.7 m. 1° of longitude = 59,274.7 × cos(lat) m.
- **Elevation file:** 106,694 × 53,347 px, 0.003374120830641°/px (200 m at the equator),
  int16 metres above the MOLA areoid, range -8,528 to 21,226, nodata -32768. Row 0 is north.
