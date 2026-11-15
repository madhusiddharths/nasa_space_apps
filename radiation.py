"""Radiation layer: surface dose rate from galactic cosmic rays (GCR), and terrain shelter.

What is MEASURED and what is MODELLED (see DATA_SOURCES.md for links):

  Measured   Curiosity RAD at Gale crater, Aug 2012 - Jun 2013 (Hassler et al. 2014):
             absorbed dose 0.210 +/- 0.040 mGy/day, dose equivalent 0.64 +/- 0.12 mSv/day.
             This is the anchor: the model returns exactly these values at the landing
             site, with the elevation and sky that the model sees there.
  Measured   Curiosity RAD parked beside butte M12, sols 1456-1467 (Ehresmann et al. 2021):
             19% of the sky blocked -> dose rate down 4%. This sets the shelter strength.
  Modelled   Change with elevation. Lower ground has more atmosphere overhead, so less GCR.
             We use an exponential atmosphere and an exponential attenuation whose length is
             chosen so that the highest and lowest terrain on Mars differ by a factor of 2,
             the range of the Odyssey MARIE + MOLA dose map (NASA PIA03480, 10-20 rem/yr).
  Modelled   Sky blocked by terrain, from the 200 m elevation grid. Cliffs and buttes smaller
             than 200 m are invisible to it, so shelter values are a LOWER bound.

Not modelled: solar particle events and the solar cycle (use the `multiplier` argument of
route_dose for "what if" scenarios), dust storms, seasonal pressure changes.

Grids follow the team convention: lon/lat degrees on wkid 104971, row 0 is north.

Elevation comes from the local DEM (elevation.py) when it is present. Without the 15 GB
download, the Gale crater window alone is fetched once from USGS and cached in
data/radiation/, so this layer works in Gale either way.

Run `python radiation.py` to build the caches and print a summary.
"""
import math
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

import elevation
import tiles
from tiles import TILE_PX

# ---- Measurements (anchors) ----
RAD_DOSE_MGY_DAY = 0.210      # Hassler et al. 2014, absorbed dose, +/- 0.040
RAD_DOSE_EQ_MSV_DAY = 0.64    # Hassler et al. 2014, dose equivalent, +/- 0.12
RAD_SITE = (137.4417, -4.5895)        # Bradbury Landing, lon/lat
SHELTER_SKY_BLOCKED = 0.19    # Ehresmann et al. 2021, butte M12
SHELTER_DOSE_DROP = 0.04      # ... and the dose drop RAD saw there

# ---- Model assumptions ----
DATUM_PRESSURE_PA = 610.0     # mean pressure at 0 m elevation
MARS_GRAVITY = 3.71           # m/s^2
SCALE_HEIGHT_M = 11100.0      # atmospheric scale height
MAP_DOSE_RATIO = 2.0          # PIA03480: 10 rem/yr (lowest ground) to 20 rem/yr (highest)
ELEV_MIN_M, ELEV_MAX_M = -8528.0, 21226.0   # range of the global DEM

# ---- Planning numbers ----
CAREER_LIMIT_MSV = 600.0      # NASA-STD-3001 career limit (for context only)
DEFAULT_EVA_BUDGET_MSV = 0.3  # team-chosen planning budget per excursion, NOT a NASA limit

# ---- Gale crater study area: (west, south, east, north) and grid shape at 200 m ----
GALE_BOX = (136.5, -6.0, 139.0, -4.0)
GALE_SHAPE = (593, 741)
HORIZON_RADIUS_M = 20000.0
HORIZON_AZIMUTHS = 16

REMOTE_DEM = ("/vsicurl/https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/"
              "Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif")
CACHE_DIR = Path(__file__).parent / "data/radiation"


# ---------------------------------------------------------------- dose model

def column_depth(elev_m):
    """Atmosphere overhead in g/cm^2 at an elevation (modelled)."""
    datum = DATUM_PRESSURE_PA / MARS_GRAVITY / 10.0   # kg/m^2 -> g/cm^2
    return datum * np.exp(-np.asarray(elev_m, dtype=np.float64) / SCALE_HEIGHT_M)


# Attenuation length that makes the model span the MARIE map's factor of 2.
ATTENUATION_G_CM2 = float((column_depth(ELEV_MIN_M) - column_depth(ELEV_MAX_M)) / math.log(MAP_DOSE_RATIO))
_anchor_values = None


def elevation_factor(elev_m):
    """Dose rate relative to the RAD landing site, from elevation alone (modelled)."""
    return np.exp((_anchor()[0] - column_depth(elev_m)) / ATTENUATION_G_CM2)


def shelter_factor(sky_blocked):
    """Dose rate relative to open sky, for a fraction of sky blocked by terrain (modelled,
    scaled to the RAD butte measurement)."""
    return 1.0 - (SHELTER_DOSE_DROP / SHELTER_SKY_BLOCKED) * np.asarray(sky_blocked)


def dose_rate(elev_m, sky_blocked=None):
    """Dose equivalent rate in mSv/day. Multiply by RAD_DOSE_MGY_DAY / RAD_DOSE_EQ_MSV_DAY
    for absorbed dose in mGy/day. sky_blocked=None means "the same sky as the landing site"."""
    rate = RAD_DOSE_EQ_MSV_DAY * elevation_factor(elev_m)
    if sky_blocked is None:
        return rate
    return rate * shelter_factor(sky_blocked) / shelter_factor(_anchor()[1])


def _anchor():
    """(column depth, sky blocked) that the model sees at the RAD landing site."""
    global _anchor_values
    if _anchor_values is None:
        g = gale()
        _anchor_values = (float(column_depth(_bilinear(g["elevation"], *RAD_SITE))),
                          float(_bilinear(g["sky_blocked"], *RAD_SITE)))
    return _anchor_values


# ---------------------------------------------------------------- Gale grids

_gale = None
_gale_lock = threading.Lock()


def gale():
    """Grids over GALE_BOX, all GALE_SHAPE float32, row 0 north:
    'elevation' (m) and 'sky_blocked' (fraction of the sky hidden by terrain, 0..1)."""
    global _gale
    with _gale_lock:
        if _gale is None:
            z = _gale_elevation()
            _gale = {"elevation": z, "sky_blocked": _cached("gale_sky_blocked.npy", lambda: sky_blocked(z, GALE_BOX))}
    return _gale


def _cached(name, build):
    path = CACHE_DIR / name
    if path.exists():
        return np.load(path)
    data = build()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, data)
    return data


def _gale_elevation():
    if elevation.DEM_AVAILABLE:
        return elevation.read_elevation(*GALE_BOX, shape=GALE_SHAPE)

    def download():
        print("radiation: fetching the Gale elevation window from USGS (one time, about 30 s)...")
        with rasterio.open(REMOTE_DEM) as dem:
            window = from_bounds(*GALE_BOX, dem.transform)
            data = dem.read(1, window=window, out_shape=GALE_SHAPE, resampling=Resampling.bilinear)
        data = data.astype(np.float32)
        data[data == elevation.NODATA] = np.nan
        return data

    return _cached("gale_elevation.npy", download)


def sky_blocked(z, box, radius_m=HORIZON_RADIUS_M, azimuths=HORIZON_AZIMUTHS):
    """Fraction of the sky hemisphere hidden behind terrain, for every cell of an elevation
    grid. Scans the horizon in `azimuths` directions out to `radius_m`; the solid angle below
    a horizon at angle h is sin(h) of the hemisphere. Cells near the grid edge see less
    terrain than really exists, so they read low."""
    west, south, east, north = box
    rows, cols = z.shape
    dy = (north - south) / rows * elevation.M_PER_DEG
    dx = (east - west) / cols * elevation.M_PER_DEG * math.cos(math.radians((north + south) / 2))
    step = min(dx, dy)
    z = np.nan_to_num(z, nan=float(np.nanmin(z)))
    r_idx, c_idx = np.arange(rows), np.arange(cols)
    total = np.zeros(z.shape, dtype=np.float64)
    for a in range(azimuths):
        az = 2 * math.pi * a / azimuths
        best = np.zeros(z.shape, dtype=np.float32)   # tan of horizon angle, never below 0
        for k in range(1, int(radius_m / step) + 1):
            d = k * step
            rr = np.clip(r_idx - int(round(d * math.cos(az) / dy)), 0, rows - 1)   # north is up
            cc = np.clip(c_idx + int(round(d * math.sin(az) / dx)), 0, cols - 1)
            # planet curvature drops distant terrain by d^2 / 2R
            rise = z[rr[:, None], cc[None, :]] - z - d * d / (2 * elevation.MARS_RADIUS_M)
            np.maximum(best, rise / d, out=best)
        total += best / np.sqrt(1 + best.astype(np.float64) ** 2)   # sin(atan(t))
    return (total / azimuths).astype(np.float32)


def _bilinear(grid, lon, lat, box=GALE_BOX):
    """Sample a box-aligned grid at lon/lat (scalars or arrays). NaN outside the box."""
    west, south, east, north = box
    rows, cols = grid.shape
    lon, lat = np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64)
    x = np.clip((lon - west) / (east - west) * cols - 0.5, 0, cols - 1)
    y = np.clip((north - lat) / (north - south) * rows - 0.5, 0, rows - 1)
    x0, y0 = np.minimum(x.astype(int), cols - 2), np.minimum(y.astype(int), rows - 2)
    fx, fy = x - x0, y - y0
    top = grid[y0, x0] * (1 - fx) + grid[y0, x0 + 1] * fx
    bottom = grid[y0 + 1, x0] * (1 - fx) + grid[y0 + 1, x0 + 1] * fx
    out = top * (1 - fy) + bottom * fy
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    return np.where(inside, out, np.nan)


def dose_grid(west, south, east, north, shape):
    """Dose equivalent rate (mSv/day) on a lon/lat box and array shape, for combining with
    the other layers. Terrain shelter is included inside GALE_BOX; elsewhere it needs the
    local DEM and is elevation-only. NaN where there is no elevation."""
    lat, lon = tiles.cell_centres(west, south, east, north, *shape)
    lon, lat = np.meshgrid(lon, lat)
    g = gale()
    blocked = np.nan_to_num(_bilinear(g["sky_blocked"], lon, lat), nan=_anchor()[1])
    if elevation.DEM_AVAILABLE:
        z = elevation.read_elevation(west, south, east, north, shape=shape)
    else:
        z = _bilinear(g["elevation"], lon, lat)
    return dose_rate(z, blocked).astype(np.float32)


# ---------------------------------------------------------------- crew-facing values

def at_point(lon, lat, multiplier=1.0):
    """Safety-card values for one place. None outside the Gale study area."""
    g = gale()
    z = float(_bilinear(g["elevation"], lon, lat))
    if math.isnan(z):
        return None
    blocked = float(_bilinear(g["sky_blocked"], lon, lat))
    rate = float(dose_rate(z, blocked)) * multiplier
    return {
        "lon": lon, "lat": lat,
        "elevation_m": round(z, 1),
        "sky_blocked_pct": round(blocked * 100, 2),
        "dose_eq_msv_per_day": round(rate, 4),
        "dose_eq_usv_per_hour": round(rate * 1000 / 24, 2),
        "absorbed_mgy_per_day": round(rate * RAD_DOSE_MGY_DAY / RAD_DOSE_EQ_MSV_DAY, 4),
        "vs_landing_site_pct": round((rate / multiplier / RAD_DOSE_EQ_MSV_DAY - 1) * 100, 2),
        "kind": "modelled estimate, anchored to Curiosity RAD",
    }


def route_dose(points, speed_kmh=3.0, stop_minutes=None, multiplier=1.0, budget_msv=DEFAULT_EVA_BUDGET_MSV):
    """Dose along a walk.

    points        [[lon, lat], ...] in order, inside the Gale study area
    speed_kmh     walking speed (time on each leg = distance / speed)
    stop_minutes  minutes spent at each point (same length as points), default 0
    multiplier    scales every dose rate, for "solar event" what-if scenarios (1 = quiet
                  conditions as RAD measured them)
    budget_msv    planning budget for the whole walk; crossing it raises a warning
    """
    stop_minutes = list(stop_minutes or [0] * len(points))
    if len(stop_minutes) != len(points):
        raise ValueError("stop_minutes must have one entry per point")
    cards = [at_point(lon, lat, multiplier) for lon, lat in points]
    if any(c is None for c in cards):
        raise ValueError(f"every point must be inside the Gale study area {GALE_BOX}")

    g = gale()
    total_usv, total_min, legs, stops, warnings = 0.0, 0.0, [], [], []

    def add(usv, minutes, label):
        nonlocal total_usv, total_min
        before = total_usv
        total_usv += usv
        total_min += minutes
        if budget_msv and before < budget_msv * 1000 <= total_usv:
            warnings.append(f"Dose budget of {budget_msv} mSv is crossed {label}.")

    for i, card in enumerate(cards):
        usv = card["dose_eq_usv_per_hour"] * stop_minutes[i] / 60
        add(usv, stop_minutes[i], f"during the stop at point {i}")
        stops.append({**card, "index": i, "stop_minutes": stop_minutes[i],
                      "stop_dose_usv": round(usv, 2), "cumulative_usv": round(total_usv, 2)})
        if i + 1 == len(points):
            break
        (lon0, lat0), (lon1, lat1) = points[i], points[i + 1]
        dist = _distance_m(lon0, lat0, lon1, lat1)
        n = max(2, int(dist / 100) + 1)                      # a sample about every 100 m
        t = np.linspace(0, 1, n)
        lons, lats = lon0 + (lon1 - lon0) * t, lat0 + (lat1 - lat0) * t
        rates = dose_rate(_bilinear(g["elevation"], lons, lats), _bilinear(g["sky_blocked"], lons, lats))
        rate = float(np.mean(rates)) * multiplier            # mSv/day
        minutes = dist / 1000 / speed_kmh * 60
        usv = rate * 1000 / 24 * minutes / 60
        add(usv, minutes, f"on leg {i} (point {i} to {i + 1})")
        legs.append({"from": i, "to": i + 1, "distance_m": round(dist, 1), "minutes": round(minutes, 1),
                     "mean_dose_eq_msv_per_day": round(rate, 4), "dose_usv": round(usv, 2),
                     "cumulative_usv": round(total_usv, 2)})

    total_msv = total_usv / 1000
    return {
        "legs": legs, "stops": stops, "warnings": warnings,
        "total_minutes": round(total_min, 1),
        "total_dose_usv": round(total_usv, 2),
        "total_dose_msv": round(total_msv, 4),
        "budget_msv": budget_msv,
        "budget_used_pct": round(total_msv / budget_msv * 100, 1) if budget_msv else None,
        "career_limit_used_pct": round(total_msv / CAREER_LIMIT_MSV * 100, 4),
        "multiplier": multiplier,
        "kind": "modelled estimate, anchored to Curiosity RAD; budget is a team planning number, not a NASA limit",
    }


def _distance_m(lon0, lat0, lon1, lat1):
    p0, p1 = math.radians(lat0), math.radians(lat1)
    a = math.sin((p1 - p0) / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(math.radians(lon1 - lon0) / 2) ** 2
    return 2 * elevation.MARS_RADIUS_M * math.asin(math.sqrt(a))


def shelters(count=12, min_blocked=0.03, spacing_cells=10):
    """The best-sheltered places in the Gale study area as GeoJSON points: local peaks of
    sky_blocked, at least `spacing_cells` (2 km) apart."""
    g = gale()
    blocked = g["sky_blocked"]
    rows, cols = blocked.shape
    pad = np.pad(blocked, spacing_cells, constant_values=-1)
    peak = np.ones(blocked.shape, dtype=bool)
    for dr in range(-spacing_cells, spacing_cells + 1):
        for dc in range(-spacing_cells, spacing_cells + 1):
            if dr or dc:
                peak &= blocked >= pad[spacing_cells + dr:spacing_cells + dr + rows,
                                       spacing_cells + dc:spacing_cells + dc + cols]
    margin = int(HORIZON_RADIUS_M / 200 / 4)       # skip the rim of the grid, where the scan is cut short
    peak[:margin] = peak[-margin:] = False
    peak[:, :margin] = peak[:, -margin:] = False
    rr, cc = np.nonzero(peak & (blocked >= min_blocked))
    order = np.argsort(-blocked[rr, cc])[:count]
    west, south, east, north = GALE_BOX
    features = []
    for rank, i in enumerate(order, 1):
        lon = west + (cc[i] + 0.5) * (east - west) / cols
        lat = north - (rr[i] + 0.5) * (north - south) / rows
        card = at_point(float(lon), float(lat))
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(float(lon), 5), round(float(lat), 5)]},
            "properties": {"rank": rank, "name": f"Shelter {rank}", **{k: card[k] for k in (
                "elevation_m", "sky_blocked_pct", "dose_eq_msv_per_day", "vs_landing_site_pct")},
                "note": "Modelled from 200 m terrain; real shelter from nearby cliffs may be better."},
        })
    return {"type": "FeatureCollection", "features": features}


def info():
    """Every number behind the layer, for the legend and for judges."""
    return {
        "measured": {
            "rad_absorbed_mgy_per_day": RAD_DOSE_MGY_DAY,
            "rad_dose_eq_msv_per_day": RAD_DOSE_EQ_MSV_DAY,
            "rad_site_lon_lat": RAD_SITE,
            "butte_sky_blocked": SHELTER_SKY_BLOCKED,
            "butte_dose_drop": SHELTER_DOSE_DROP,
        },
        "modelled": {
            "datum_pressure_pa": DATUM_PRESSURE_PA,
            "scale_height_m": SCALE_HEIGHT_M,
            "attenuation_g_cm2": round(ATTENUATION_G_CM2, 2),
            "marie_map_dose_ratio": MAP_DOSE_RATIO,
            "horizon_radius_m": HORIZON_RADIUS_M,
            "terrain_resolution_m": 200,
        },
        "planning": {"career_limit_msv": CAREER_LIMIT_MSV, "default_eva_budget_msv": DEFAULT_EVA_BUDGET_MSV},
        "study_area_west_south_east_north": GALE_BOX,
        "color_scales": {"dose": DOSE_SCALE, "shelter": SHELTER_SCALE},
    }


# ---------------------------------------------------------------- map tiles

# Tiling scheme in tiles.py.
DOSE_SCALE = (0.60, 0.80)       # mSv/day, colours clamp outside this
SHELTER_SCALE = (0.05, 0.25)    # fraction of sky blocked; below the low end is transparent
_VIRIDIS = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=np.float64)
_SHELTER = np.array([[255, 255, 255], [64, 224, 208], [0, 96, 160]], dtype=np.float64)
_EMPTY = tiles.png(np.zeros((TILE_PX, TILE_PX, 4), dtype=np.uint8))


def _colors(t, ramp):
    t = np.clip(np.nan_to_num(t, nan=0.0), 0, 1) * (len(ramp) - 1)
    i = np.minimum(t.astype(int), len(ramp) - 2)
    f = (t - i)[..., None]
    return ramp[i] * (1 - f) + ramp[i + 1] * f


def tile_png(kind, level, row, col):
    """PNG map tile. kind: 'dose' (dose equivalent rate) or 'shelter' (sky blocked)."""
    west, south, east, north = tiles.bounds(level, row, col)
    gw, gs, ge, gn = GALE_BOX
    in_gale = west < ge and east > gw and south < gn and north > gs
    rgba = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.uint8)
    if kind == "dose":
        if not in_gale and not elevation.DEM_AVAILABLE:
            return _EMPTY
        value = dose_grid(west, south, east, north, (TILE_PX, TILE_PX))
        rgba[..., :3] = _colors((value - DOSE_SCALE[0]) / (DOSE_SCALE[1] - DOSE_SCALE[0]), _VIRIDIS)
        rgba[..., 3] = np.where(np.isnan(value), 0, 200)
    elif kind == "shelter":
        if not in_gale:
            return _EMPTY
        lat, lon = tiles.cell_centres(west, south, east, north, TILE_PX, TILE_PX)
        value = _bilinear(gale()["sky_blocked"], *np.meshgrid(lon, lat))
        t = np.nan_to_num((value - SHELTER_SCALE[0]) / (SHELTER_SCALE[1] - SHELTER_SCALE[0]), nan=0.0)
        rgba[..., :3] = _colors(t, _SHELTER)
        rgba[..., 3] = np.clip(t * 3, 0, 1) * 220          # open sky is transparent
    else:
        raise ValueError("kind must be 'dose' or 'shelter'")
    return tiles.png(rgba)


if __name__ == "__main__":
    g = gale()
    z, b = g["elevation"], g["sky_blocked"]
    d = dose_rate(z, b)
    print(f"Gale study area {GALE_BOX}, grid {z.shape}")
    print(f"  elevation      {np.nanmin(z):8.0f} .. {np.nanmax(z):.0f} m")
    print(f"  sky blocked    {b.min() * 100:8.2f} .. {b.max() * 100:.2f} %")
    print(f"  dose eq. rate  {np.nanmin(d):8.3f} .. {np.nanmax(d):.3f} mSv/day (modelled)")
    print(f"  attenuation length {ATTENUATION_G_CM2:.1f} g/cm2")
    print(f"  at RAD landing site: {at_point(*RAD_SITE)}")
    for f in shelters(5)["features"]:
        print("  ", f["geometry"]["coordinates"], f["properties"]["sky_blocked_pct"], "% sky blocked")
