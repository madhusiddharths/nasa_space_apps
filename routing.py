"""Astronaut routing: the safest and the quickest walk from A to B.

The ground between the two points is cut into square cells (200 m, the resolution of the
elevation data; larger for long trips). Each cell gets a hazard level from the layers:

  Slope        elevation.py   Caution 10-20 deg, Danger 20-30, Extreme over 30
  Loose dust   firmness.py    Caution where thermal inertia is under 100 (may not bear weight)
  Cold ground  temperature.py Caution below -80 C, Danger below -120 C, at the departure hour
  No data      elevation.py   Extreme (never crossed if there is any other way)

A cell's level is its worst hazard: 0 Clear, 1 Caution, 2 Danger, 3 Extreme.

Walking speed is WALK_KMH on flat firm ground, scaled by Tobler's hiking function for the
slope in the direction of travel and slowed on soft ground. Radiation dose (radiation.py)
is added up along the walk; it barely changes from place to place, so it is reported,
not steered by.

Two routes are found on the same grid:

  Safest    First the lowest hazard level that still connects A and B is found exactly
            (connected components). If that is above Clear, every possible route crosses
            ground that bad: it is UNAVOIDABLE, and reported as such. The route then never
            goes above that level, and each metre of hazardous ground counts as many
            extra metres of flat walking (SAFEST_PENALTY): it will walk up to 20 m further
            to stay off 1 m of Caution ground, 400 m for Danger.
  Quickest  Least time. Caution ground is allowed at no penalty; Danger and Extreme are
            off limits unless they are unavoidable, and then kept as short as possible.
            It is never slower than the safest route: if it would be, the safest is both.

Limits. Every threshold, speed and penalty here is a planning number chosen by the team,
not a NASA limit. Slopes are averages over a cell, so short cliffs and boulders are not
seen and real slopes are locally steeper. Firmness and temperature come from 3 km data.
"Unavoidable" means within the search area, which reaches PAD_FRACTION of the trip length
(at least PAD_MIN_M) beyond A and B. Temperature is taken at the departure hour for the
whole walk. One way only: the walk back is a second request.
"""
import math

import numpy as np
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

import elevation
import firmness
import radiation
import temperature
import tiles

# ---- The astronaut (planning numbers) ----
WALK_KMH = 3.0                        # on flat, firm ground; same default as radiation.route_dose
SOFT_GROUND_SPEED = {0: 0.5, 1: 0.8}  # speed factor by firmness class: loose dust, soft ground
MAX_EVA_HOURS = 8.0                   # one suit's worth of walking

# ---- Hazards ----
LEVELS = ["Clear", "Caution", "Danger", "Extreme"]
SLOPE_DEG = (10, 20, 30)              # lower bound of Caution, Danger, Extreme
COLD_C = (-80, -120)                  # ground colder than this is Caution, Danger
DUST_CLASS = 0                        # firmness class that counts as loose dust

# Each hazard: key, then its description at level 1, 2 and 3 (None = it never reaches that level).
HAZARDS = [
    ("slope", ("Steep slope (10–20°)", "Very steep slope (20–30°)", "Cliff-like slope (over 30°)")),
    ("dust", ("Loose dust, may not bear weight", None, None)),
    ("cold", ("Ground colder than −80 °C", "Ground colder than −120 °C", None)),
    ("nodata", (None, None, "No elevation data")),
]

# A metre of hazardous ground costs this many extra metres of flat walking, per hazard, by level.
SAFEST_PENALTY = (0, 20, 400, 8000)
QUICKEST_PENALTY = (0, 0, 400, 8000)  # Caution is free; the rest is only ever crossed when unavoidable

# ---- Search grid ----
MIN_CELL_M = 200                      # elevation data resolution
MAX_CELLS = 250_000                   # longer trips use larger cells to stay under this
PAD_FRACTION, PAD_MIN_M = 0.6, 4000   # how far beyond A and B a detour may go
MAX_TRIP_KM = 100                     # straight-line; beyond this it is not a walk

# Moves from a cell: the 8 neighbours plus the 8 knight moves, for smoother paths.
MOVES = [(dr, dc) for dr in range(-2, 3) for dc in range(-2, 3)
         if max(abs(dr), abs(dc)) == 1 or abs(dr * dc) == 2]


def _cells_crossed(dr, dc):
    """Offsets of every cell a move touches: both ends, plus the two a knight move passes between."""
    if abs(dr) == 2:
        return [(0, 0), (dr // 2, 0), (dr // 2, dc), (dr, dc)]
    if abs(dc) == 2:
        return [(0, 0), (0, dc // 2), (dr, dc // 2), (dr, dc)]
    return [(0, 0), (dr, dc)]


def _tobler(gradient):
    """Walking speed relative to flat ground for a rise-over-run gradient in the direction
    of travel (Tobler's hiking function: fastest on a gentle descent)."""
    return np.exp(-3.5 * np.abs(gradient + 0.05) + 3.5 * 0.05)


def _move_seconds(horizontal_m, climb_m, ground_speed):
    """Time to walk one move: surface distance over slope- and ground-adjusted speed."""
    speed = WALK_KMH / 3.6 * _tobler(climb_m / horizontal_m) * ground_speed
    return np.hypot(horizontal_m, climb_m) / speed


class Grid:
    """The search area as arrays of one shape, row 0 north: elevation, hazards, speeds."""

    def __init__(self, start, end, ls, local_time):
        trip_m = _distance_m(*start, *end)
        if trip_m > MAX_TRIP_KM * 1000:
            raise ValueError(f"A and B are {trip_m / 1000:.0f} km apart; walking routes go up to {MAX_TRIP_KM} km")
        (lon_a, lat_a), (lon_b, lat_b) = start, end
        if abs(lon_a - lon_b) > 180:
            raise ValueError("routes across the 180° meridian are not supported")
        cos_lat = math.cos(math.radians((lat_a + lat_b) / 2))
        pad_m = max(PAD_FRACTION * trip_m, PAD_MIN_M)
        pad_lat, pad_lon = pad_m / elevation.M_PER_DEG, pad_m / elevation.M_PER_DEG / cos_lat
        west, east = max(min(lon_a, lon_b) - pad_lon, -180), min(max(lon_a, lon_b) + pad_lon, 180)
        south, north = max(min(lat_a, lat_b) - pad_lat, -89), min(max(lat_a, lat_b) + pad_lat, 89)
        if not (south <= min(lat_a, lat_b) and max(lat_a, lat_b) <= north):
            raise ValueError("routes within 1° of a pole are not supported")
        height_m = (north - south) * elevation.M_PER_DEG
        width_m = (east - west) * elevation.M_PER_DEG * cos_lat
        self.cell_m = max(MIN_CELL_M, math.sqrt(height_m * width_m / MAX_CELLS))
        self.shape = rows, cols = math.ceil(height_m / self.cell_m), math.ceil(width_m / self.cell_m)
        self.box = box = (west, south, east, north)
        self.lats, self.lons = tiles.cell_centres(*box, rows, cols)
        self.dy = height_m / rows                                               # metres per row
        self.dx = (east - west) / cols * elevation.M_PER_DEG * np.cos(np.radians(self.lats))  # per column, by row

        self.z = elevation.read_elevation(*box, shape=self.shape)
        self.slope = elevation.slope_degrees(self.z, south=south, north=north, west=west, east=east)
        ground = firmness.firmness_class(firmness.read_thermal_inertia(*box, shape=self.shape))
        self.celsius = temperature.read_temperature(*box, ls=ls, local_time=local_time, shape=self.shape) - 273.15
        dose = radiation.dose_grid(*box, shape=self.shape)                      # mSv per day
        self.dose = np.nan_to_num(dose, nan=float(np.nanmean(dose)))

        nodata = np.isnan(self.z) | np.isnan(self.slope)
        self.hazard = np.stack([                                                # level of each of HAZARDS
            np.where(nodata, 0, np.digitize(self.slope, SLOPE_DEG)),
            ground == DUST_CLASS,
            np.digitize(-self.celsius, [-c for c in COLD_C]),
            nodata * 3,
        ]).astype(np.uint8)
        self.level = self.hazard.max(axis=0)
        self.ground_speed = np.ones(self.shape, np.float32)
        for firmness_class, factor in SOFT_GROUND_SPEED.items():
            self.ground_speed[ground == firmness_class] = factor
        self.z = np.nan_to_num(self.z)

    def cell(self, lon, lat):
        """(row, col) of the cell holding a lon/lat point."""
        west, south, east, north = self.box
        rows, cols = self.shape
        return (min(int((north - lat) / (north - south) * rows), rows - 1),
                min(int((lon - west) / (east - west) * cols), cols - 1))

    def lowest_connecting_level(self, levels, a, b):
        """The lowest L such that a and b are joined by cells whose `levels` are all <= L.
        Every route from a to b crosses a cell of at least this level."""
        for limit in range(len(LEVELS)):
            regions, _ = ndimage.label(levels <= limit, structure=np.ones((3, 3)))
            if regions[a] and regions[a] == regions[b]:
                return limit
        return len(LEVELS) - 1

    def moves(self):
        """Every move on the grid as flat arrays: from-cell, to-cell, seconds, metres, and
        the level of each hazard (the worst among the cells the move touches)."""
        rows, cols = self.shape
        index = np.arange(rows * cols, dtype=np.int32).reshape(self.shape)
        out = []
        for dr, dc in MOVES:
            r0, r1, c0, c1 = max(0, -dr), rows - max(0, dr), max(0, -dc), cols - max(0, dc)

            def shifted(a, r=0, c=0):
                return a[..., r0 + r:r1 + r, c0 + c:c1 + c]

            crossed = _cells_crossed(dr, dc)
            hazard = np.maximum.reduce([shifted(self.hazard, r, c) for r, c in crossed])
            ground_speed = np.minimum.reduce([shifted(self.ground_speed, r, c) for r, c in crossed])
            horizontal = np.hypot(dr * self.dy, dc * shifted(self.dx[:, None] * np.ones((1, cols))))
            climb = shifted(self.z, dr, dc) - shifted(self.z)
            seconds = _move_seconds(horizontal, climb, ground_speed)
            out.append((shifted(index).ravel(), shifted(index, dr, dc).ravel(), seconds.ravel(),
                        np.hypot(horizontal, climb).ravel(), hazard.reshape(len(HAZARDS), -1)))
        return tuple(np.concatenate(part, axis=-1) for part in zip(*out))


def _shortest_path(cell_count, frm, to, cost, a, b):
    """Cells of the least-cost path from a to b (flat indices), or None if there is none."""
    graph = csr_matrix((cost, (frm, to)), shape=(cell_count, cell_count))
    _, before = dijkstra(graph, indices=a, return_predecessors=True)
    if before[b] < 0:
        return None
    path = [b]
    while path[-1] != a:
        path.append(before[path[-1]])
    return path[::-1]


def _distance_m(lon0, lat0, lon1, lat1):
    p0, p1 = math.radians(lat0), math.radians(lat1)
    a = math.sin((p1 - p0) / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(math.radians(lon1 - lon0) / 2) ** 2
    return 2 * elevation.MARS_RADIUS_M * math.asin(math.sqrt(a))


def _describe(grid, path, start, end, unavoidable, penalty):
    """Everything the viewer shows for one route: its line, totals and hazard stretches.

    unavoidable[h] is the level of hazard h that no route can stay under. A hazard on this
    route is tagged unavoidable when it is exactly that level and the route was penalised
    for it, so the tagged stretches are as short as the route could make them."""
    rows, cols = grid.shape
    cells = [divmod(int(i), cols) for i in path]
    line = [[float(grid.lons[c]), float(grid.lats[r])] for r, c in cells]
    line[0], line[-1] = list(start), list(end)

    totals = dict(distance=0.0, seconds=0.0, climb=0.0, descent=0.0, dose_usv=0.0)
    stretches = []                                   # consecutive moves with the same hazards
    for i, ((r, c), (r2, c2)) in enumerate(zip(cells, cells[1:])):
        dr, dc = r2 - r, c2 - c
        crossed = [(r + a, c + b) for a, b in _cells_crossed(dr, dc)]
        horizontal = math.hypot(dr * grid.dy, dc * grid.dx[r])
        climb = float(grid.z[r2, c2] - grid.z[r, c])
        seconds = float(_move_seconds(horizontal, climb, min(grid.ground_speed[cell] for cell in crossed)))
        metres = math.hypot(horizontal, climb)
        totals["distance"] += metres
        totals["seconds"] += seconds
        totals["climb" if climb > 0 else "descent"] += abs(climb)
        totals["dose_usv"] += (grid.dose[r, c] + grid.dose[r2, c2]) / 2 * 1000 / 86400 * seconds

        hazard = np.max([grid.hazard[:, a, b] for a, b in crossed], axis=0)
        level = int(hazard.max())
        if level == 0:
            continue
        found = tuple((h, int(hazard[h])) for h in range(len(HAZARDS)) if hazard[h])
        if stretches and stretches[-1]["to"] == i and stretches[-1]["found"] == found:
            stretch = stretches[-1]
        else:
            stretch = dict(found=found, level=level, start=i, to=i, distance_m=0.0, minutes=0.0)
            stretches.append(stretch)
        stretch["to"] = i + 1
        stretch["distance_m"] += metres
        stretch["minutes"] += seconds / 60

    def forced(h, lv):
        return lv == unavoidable[h] and penalty[lv] > 0

    hazards = {}                                     # the same, added up per hazard description
    for stretch in stretches:
        found = stretch.pop("found")
        stretch["hazards"] = [HAZARDS[h][1][lv - 1] for h, lv in found]
        stretch["unavoidable"] = any(forced(h, lv) for h, lv in found)
        stretch["from"] = stretch.pop("start")       # line[from] .. line[to] is the stretch
        stretch["distance_m"] = round(stretch["distance_m"])
        stretch["minutes"] = round(stretch["minutes"], 1)
        for h, lv in found:
            entry = hazards.setdefault((lv, h), dict(level=lv, label=HAZARDS[h][1][lv - 1], distance_m=0,
                                                     unavoidable=forced(h, lv)))
            entry["distance_m"] += stretch["distance_m"]

    on_path = tuple(np.array(cells).T)
    hours = totals["seconds"] / 3600
    warnings = []
    if hours > MAX_EVA_HOURS:
        warnings.append(f"Takes {hours:.1f} hours, longer than one {MAX_EVA_HOURS:.0f}-hour EVA.")
    if totals["dose_usv"] > radiation.DEFAULT_EVA_BUDGET_MSV * 1000:
        warnings.append(f"Radiation dose is over the {radiation.DEFAULT_EVA_BUDGET_MSV} mSv planning budget for one excursion.")
    return {
        "line": line,
        "distance_km": round(totals["distance"] / 1000, 2),
        "minutes": round(totals["seconds"] / 60),
        "climb_m": round(totals["climb"]),
        "descent_m": round(totals["descent"]),
        "dose_usv": round(float(totals["dose_usv"]), 1),
        "max_slope_deg": round(float(np.nanmax(grid.slope[on_path])), 1),
        "coldest_c": round(float(grid.celsius[on_path].min())),
        "worst_level": max((s["level"] for s in stretches), default=0),
        "hazards": [hazards[key] for key in sorted(hazards, reverse=True)],
        "stretches": stretches,
        "warnings": warnings,
    }


def plan(start, end, ls=90.0, local_time=12.0):
    """The safest and the quickest walk between two [lon, lat] points.

    ls          season, solar longitude in degrees (see temperature.py)
    local_time  departure, local true solar time in hours; sets how cold the ground is

    Returns a dict the viewer draws directly; see _describe for what each route holds.
    Raises ValueError if the points are too far apart or the trip cannot be gridded.
    """
    start, end = [float(v) for v in start], [float(v) for v in end]
    grid = Grid(start, end, ls, local_time)
    a, b = grid.cell(*start), grid.cell(*end)
    if a == b:
        raise ValueError(f"A and B are in the same {grid.cell_m:.0f} m cell; pick points further apart")

    # What no route can avoid: overall, and for each hazard on its own.
    floor = grid.lowest_connecting_level(grid.level, a, b)
    unavoidable = [grid.lowest_connecting_level(levels, a, b) for levels in grid.hazard]
    if floor > max(unavoidable):          # avoidable one at a time, but not all at once
        unavoidable = [floor] * len(HAZARDS)

    frm, to, seconds, metres, hazard = grid.moves()
    worst = hazard.max(axis=0)
    cols = grid.shape[1]
    flat_a, flat_b = a[0] * cols + a[1], b[0] * cols + b[1]
    routes = {}
    for name, penalty, ceiling in (("safest", SAFEST_PENALTY, floor), ("quickest", QUICKEST_PENALTY, max(floor, 1))):
        allowed = worst <= ceiling
        extra_metres = metres[allowed] * sum(np.asarray(penalty, np.float32)[levels[allowed]] for levels in hazard)
        cost = seconds[allowed] + extra_metres / (WALK_KMH / 3.6)
        path = _shortest_path(grid.z.size, frm[allowed], to[allowed], cost, flat_a, flat_b)
        routes[name] = _describe(grid, path, start, end, unavoidable, penalty)
    safest, quickest = routes["safest"], routes["quickest"]
    if quickest["minutes"] > safest["minutes"]:
        # Happens when Danger is unavoidable: shaving a little more of it off cost a long
        # detour. Then nothing quicker is acceptably safe, and the safest route is both.
        quickest = routes["quickest"] = dict(safest)
    quickest["same_as_safest"] = quickest["line"] == safest["line"]
    # The quickest route is not penalised for Caution ground, so its Caution is tagged
    # unavoidable only where it crosses no more of it than the safest route had to.
    least = {h["label"]: h["distance_m"] for h in safest["hazards"] if h["unavoidable"]}
    forced = {h["label"] for h in quickest["hazards"] if h["distance_m"] <= 1.02 * least.get(h["label"], -1)}
    for item in quickest["hazards"] + quickest["stretches"]:
        item["unavoidable"] = item["unavoidable"] or bool(forced & {item.get("label"), *item.get("hazards", [])})

    if floor == 0:
        verdict = "A route on clear ground exists."
    else:
        worst_kinds = [HAZARDS[h][1][floor - 1] for h in range(len(HAZARDS)) if unavoidable[h] >= floor]
        verdict = (f"No route avoids {LEVELS[floor]} ground. Every way from A to B crosses: "
                   + "; ".join(kind for kind in worst_kinds if kind) + ".")
    return {
        "start": start, "end": end,
        "straight_km": round(_distance_m(*start, *end) / 1000, 2),
        "cell_m": round(grid.cell_m),
        "search_box": list(grid.box),
        "ls": ls, "local_time": local_time,
        "unavoidable_level": floor,
        "verdict": verdict,
        "routes": routes,
    }


def legend():
    """Hazard levels, their colours on the map, and the numbers behind the routes."""
    return {
        "levels": [{"level": i, "label": label} for i, label in enumerate(LEVELS)],
        "walk_kmh": WALK_KMH, "max_eva_hours": MAX_EVA_HOURS,
        "slope_deg": SLOPE_DEG, "cold_c": COLD_C,
        "note": "Planning numbers chosen by the team, not NASA limits. Terrain is seen at "
                f"{MIN_CELL_M} m, ground firmness and temperature at 3 km.",
    }


if __name__ == "__main__":
    result = plan(radiation.RAD_SITE, (137.38, -4.72))        # Bradbury Landing to the foot of Mount Sharp
    print(result["verdict"], f"({result['straight_km']} km straight, {result['cell_m']} m cells)")
    for name, route in result["routes"].items():
        print(f"  {name:8s} {route['distance_km']:6.2f} km  {route['minutes']:4d} min  +{route['climb_m']} m  "
              f"{route['dose_usv']} uSv  worst: {LEVELS[route['worst_level']]}")
        for h in route["hazards"]:
            print(f"           {LEVELS[h['level']]}: {h['label']}, {h['distance_m']} m"
                  + (" (unavoidable)" if h["unavoidable"] else ""))
