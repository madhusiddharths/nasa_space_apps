# Data sources

Where every dataset comes from, what you have to download after cloning, and the GIS
conventions all layers share.

## Download after cloning

The `data/` folder is not in git. Create it inside the cloned repo and download:

| Dataset | Size | Goes in | Link |
|---|---|---|---|
| Mars HRSC + MOLA blended elevation, 200 m, v2 (USGS) | 11.4 GB | `data/elevation/` | [Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) |
| Its overview sidecar (low-resolution copies) | 3.8 GB | `data/elevation/` | [Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr) |
| MGS TES nightside thermal inertia, 3 km (Putzig & Mellon 2007, NASA PDS) | 52 MB | `data/thermal_inertia/` | [global_ti_night_2007.img](https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/global_ti_night_2007.img) |
| SWIM ice consistency, 0–1 m, 1–5 m and >5 m depth, 3 km (PSI/NASA) | 3 × 71 MB | `data/water_ice/` | [SWIM4MIM_Ci_0_1.tif](https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_0_1.tif), [SWIM4MIM_Ci_1_5.tif](https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_1_5.tif), [SWIM4MIM_Ci_5.tif](https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_5.tif) |
| Polar ice units `lApc` and `Apu` from the USGS geologic map of Mars (SIM 3292) | 1 MB | `data/water_ice/` | query of the [USGS feature service](https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3), command below |

Both elevation files are required and must keep these names. Without the `.ovr` file, zoomed-out
reads take seconds instead of milliseconds.

Each command below runs from the repo root and resumes if interrupted.

Elevation:

```bash
mkdir -p data/elevation && cd data/elevation && curl -L -C - -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif -O https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr
```

Dataset page: https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m

Optional: `python scripts/build_elevation_cog.py` writes a tiled, compressed copy of the two
elevation files into the same folder (`..._v2_cog.tif`, 3.8 GB against 15.2 GB, a few
minutes). It holds exactly the same heights, with the low-resolution copies inside the one
file. `elevation.py` uses the copy when it is there and the original two files when it is
not, so the copy alone is enough on a server.

Thermal inertia:

```bash
mkdir -p data/thermal_inertia && cd data/thermal_inertia && curl -L -C - -O https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/global_ti_night_2007.img -O https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/global_ti_night_2007.lbl
```

Dataset page: https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html

Water ice, needed only to rebuild `ice_data/` with `scripts/build_ice_grid.py` (three SWIM maps, then the polar ice outlines):

```bash
mkdir -p data/water_ice && cd data/water_ice && curl -L -C - -O https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_0_1.tif -O https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_1_5.tif -O https://swim.psi.edu/output/SWIM4MIM/Global/Composite/SWIM4MIM_Ci_5.tif
```

```bash
curl -G "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3/query" --data-urlencode "where=Unit IN ('lApc','Apu')" --data-urlencode "outFields=Unit,UnitDesc" --data-urlencode "f=geojson" -o data/water_ice/polar_surface_ice.geojson
```

Dataset pages: https://swim.psi.edu/SWIM4MIMProducts.php and https://pubs.usgs.gov/publication/sim3292

Expected layout:

```
data/
  elevation/
    Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif
    Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif.ovr
    Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif   optional, made by scripts/build_elevation_cog.py
  thermal_inertia/
    global_ti_night_2007.img
    global_ti_night_2007.lbl
  water_ice/
    SWIM4MIM_Ci_0_1.tif
    SWIM4MIM_Ci_1_5.tif
    SWIM4MIM_Ci_5.tif
    polar_surface_ice.geojson
  radiation/            created by radiation.py on first use (cached grids)
  tiles/                optional, made by scripts/build_static_tiles.py (tiles drawn ahead of time)
  measurements/         made by scripts/measure_tiles.py
```

## Optional: 100 m temperature detail

The temperature layer works without any download, at 3.7 km per pixel. For 100 m detail,
download the THEMIS quantitative thermal inertia tile(s) covering your area into
`data/temperature/` (2.5 GB each, keep the file name). `temperature.py` uses them automatically.

Tiles are 60° of longitude by 30° of latitude, named by their south-west corner with
longitude in 0-360°E: latitude `60S`, `30S`, `00N` or `30N`, longitude `000E` to `300E`.
Gale and Gusev are in `30S120E`, Jezero in `00N060E`, Meridiani in `30S300E`.

```bash
mkdir -p data/temperature && cd data/temperature && curl -L -C - -O https://asc-astropedia.s3.us-west-2.amazonaws.com/Mars/Odyssey/THEMIS-Global-Thermal-Inertia-Mosaic/Quantitative-32-Bit/ancillary/THEMIS_TI_Mosaic_Quant_30S120E_100mpp.tif
```

Dataset page: https://astrogeology.usgs.gov/search/map/mars-themis-derived-global-thermal-inertia-mosaic

## Already in the repo (`ice_data/`)

Read by `ice.py`. Rebuild with `scripts/build_ice_grid.py` (not needed to run the app; it
needs the SWIM maps and the polar ice outlines in `data/water_ice/`, commands above).

| File | What it is | Source |
|---|---|---|
| `mars_ice_weights_20ppd.tif` | Water ice by depth, whole planet at 20 px/deg (3 km). Four bands: on the surface, within 1 m, 1 to 5 m, deeper than 5 m. Each value is 0 to 255 for a weight 0 to 1 that ice of that class is present (128 = SWIM score 0.3) | The three SWIM maps, smoothed, merged with the USGS polar ice units. SWIM project (PSI/NASA/JPL); Tanaka et al. 2014 |

## Already in the repo (`temperature_data/`)

Read by `temperature.py`. Rebuild with the scripts in `scripts/` (not needed to run the app).

| File | What it is | Source |
|---|---|---|
| `mars_thermal_inertia_16ppd.tif` | Thermal inertia, whole planet at 16 px/deg (3.7 km). Band 1: value in J m⁻² K⁻¹ s⁻½. Band 2: 1 where THEMIS measured the cell, 0 where filled (gaps, and everything poleward of 60°, set to 200) | The 24 THEMIS quantitative tiles above, geometric mean of the 100 m pixels. 2001 Mars Odyssey, NASA/JPL/ASU, USGS |
| `mars_albedo_8ppd.tif` | Albedo × 10000, whole planet at 8 px/deg (7.4 km) | [TES global bolometric albedo](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif), Mars Global Surveyor, NASA/JPL/ASU |
| `surface_temperature_lut.npz` | Model surface temperature (K × 10) for 24 seasons × 24 hours × 37 latitudes × 12 thermal inertias × 5 albedos | Our thermal model, `scripts/build_temperature_lut.py` |

Both maps are GeoTIFFs on the shared grid below (lon -180..180, row 0 north).
## Radiation layer: sources and model

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
| `rems_ground_temperature.json` | Curiosity REMS daily low and high ground and air temperature, median per 15° of Ls, sols 1-4995 | [NASA Mars weather feed](https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json), NASA/JPL-Caltech/CAB (CSIC-INTA) |
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
- Thermal inertia: NASA/MGS/TES; Putzig & Mellon (2007), Icarus 191, 68–94
- THEMIS thermal inertia: NASA/JPL/ASU, USGS; Fergason et al. (2006), JGR 111, E12004
- Albedo: NASA/MGS/TES; Christensen et al. (2001), JGR 106, 23823–23871
- Curiosity ground temperature: NASA/JPL-Caltech/CAB (CSIC-INTA), REMS
- Atmosphere scheme of the thermal model: after N. Schorghofer's Planetary-Code-Collection
- Buried ice: Subsurface Water Ice Mapping (SWIM) project, PSI/NASA/JPL; Morgan & Putzig et al. (2025)
- Polar surface ice: Tanaka et al. (2014), Geologic Map of Mars, USGS SIM 3292
- Radiation: NASA/JPL-Caltech/SwRI (MSL RAD), NASA/JPL/JSC (Odyssey MARIE)

## GIS reference (every layer must match this)

- **Coordinate system:** `GCS_Mars_2000_Sphere`, Esri wkid **104971**. Plain lon/lat in degrees.
- **Longitude:** -180 to 180, east positive. Convert 0–360°E data with `lon > 180 ? lon - 360 : lon`.
- **Latitude:** -90 to 90, planetocentric.
- **Sphere radius:** 3,396,190 m. 1° of latitude = 59,274.7 m. 1° of longitude = 59,274.7 × cos(lat) m.
- **Elevation file:** 106,694 × 53,347 px, 0.003374120830641°/px (200 m at the equator),
  int16 metres above the MOLA areoid, range -8,528 to 21,226, nodata -32768. Row 0 is north.
- **Thermal inertia file:** raw image, no header: 7,200 × 3,600 px, 0.05°/px (3 km at the equator),
  big-endian int16 in J m⁻² K⁻¹ s⁻¹ᐟ² ("tiu"), range 5 to 5,000, nodata 0, no data beyond ±87°.
  Row 0 is north. `firmness.py` reads it; the `.lbl` file is its description.
- **SWIM ice files:** 7,200 × 2,400 px, 0.05°/px, lon -180 to 180, lat 60 to -60 only, float32
  consistency score from -1 (no ice) to +1 (ice); exactly 0 means no information.
  `scripts/build_ice_grid.py` merges the three depths with the polar ice outlines (lon/lat
  GeoJSON) into the 7,200 × 3,600 grid in `ice_data/`, which is what `ice.py` reads.
