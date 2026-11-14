"""Astronaut routing: the safest and the quickest trip from A to B, by rover and on foot.

The trip is hybrid. The crew drives as much of it as the rover can do and walks the rest:

  walk to the rover  ->  drive  ->  park  ->  walk to B

Either walk can be zero (the rover picks up at A, or drives all the way to B), and a trip
with no usable ground for the rover is walked entirely. The rover is boarded and left only
at a PARKING SPOT, and it is used for one continuous drive.

The ground between the two points is cut into square cells (200 m, the resolution of the
elevation data; larger for long trips). Each cell gets a hazard level, separately for a
person on foot and for the rover:

                 On foot                               Rover
  Slope          Caution 10-20 deg, Danger 20-30,      Caution 10-15 deg, Danger 15-25,
                 Extreme over 30                       over 25 it cannot drive
  Loose dust     Caution (may not bear weight)         Caution (wheels slip, more energy)
  Cold ground    Caution below -80 C, Danger           not a hazard inside the cabin
                 below -120 C, at the departure hour
  No data        Extreme                               cannot drive

A cell's level is its worst hazard: 0 Clear, 1 Caution, 2 Danger, 3 Extreme.

Walking speed is WALK_KMH on flat firm ground, scaled by Tobler's hiking function for the
slope in the direction of travel and slowed on soft ground.

Driving follows the ground, not a straight line. Rover speed is ROVER_KMH on flat firm
ground. Climbing costs extra: the energy to move one metre is taken as rolling resistance
plus the lift against gravity, relative to flat ground (SLOPE STRAIN, see _strain). A 10
degree climb costs about twice the energy of flat ground, and the rover slows by the same
factor. Soft ground costs more again. The rover's range is given for flat firm ground;
the route's energy is counted in "flat km" against it.

A parking spot is a cell that is level (PARK_SLOPE_DEG or less), on ground that is not
loose dust, with no steep ground in the cells around it (PARK_APPROACH_DEG or less, so the
rover can drive in and the crew can walk away), and at most Caution for a person on foot.

Two routes are found on the same grid:

  Safest    First the lowest hazard level that still connects A and B is found. If that
            is above Clear, every possible route crosses ground that bad: it is
            UNAVOIDABLE, and reported as such. The route then never goes above that
            level, and each metre of hazardous ground counts as many extra metres of flat
            travel (SAFEST_PENALTY).
  Quickest  Least time. Caution ground is allowed at no penalty; Danger and Extreme are
            off limits unless they are unavoidable, and then kept as short as possible.

In both, a minute on foot counts as WALK_AVERSION minutes of driving, so the routes walk
as little as they can.

Viability. A route is NOT VIABLE when it needs more rover energy than the rover's range,
more walking than the walking limit, a single walk longer than one EVA, or Extreme ground
on foot. If the first try is over the rover's range, the search is repeated with the
drive kept to the ground the rover can reach from where it is boarded: it parks before
the range runs out and the crew walks on from there. When nothing viable is found, the
route closest to the limits is returned with the reasons it fails.

Where the numbers come from (all are planning numbers chosen by the team, not NASA limits):
  ROVER_KMH, ROVER_RANGE_KM   NASA Space Exploration Vehicle concept (2008): 10 km/h, 125 km
  ROVER_SLOPE_DEG             the Apollo Lunar Roving Vehicle climbed slopes of about 25 deg
  MAX_WALK_KM                 NASA's EVA Walkback Test (NASA/TP-2009-214796) studied a suited
                              10 km walk back to base as the emergency case
  RECORD_WALK_KM              the longest walk actually made on another world: Apollo 14's
                              second EVA, about 2.9 km in all. Apollo 17 drove 7.6 km from
                              its lander, the furthest anyone has been from shelter.
  MAX_EVA_HOURS               longest Apollo EVA was 7 h 37 min

Limits. Slopes are averages over a cell, so short cliffs and boulders are not seen and
real slopes are locally steeper; long trips use larger cells and see less. Firmness and
temperature come from 3 km data. "Unavoidable" means within the search area, which reaches
PAD_FRACTION of the trip length (at least PAD_MIN_M) beyond A and B. Temperature is taken
at the departure hour for the whole trip. One way only: the rover's range is not halved
for the drive back, and the trip back is a second request.
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

# ---- The astronaut on foot (planning numbers) ----
WALK_KMH = 3.0                        # on flat, firm ground; same default as radiation.route_dose
SOFT_GROUND_SPEED = {0: 0.5, 1: 0.8}  # speed factor by firmness class: loose dust, soft ground
MAX_EVA_HOURS = 8.0                   # one suit's worth of walking
MAX_WALK_KM = 10.0                    # default limit on walking in one trip (walkback distance)
RECORD_WALK_KM = 2.9                  # longest walk made on another world (Apollo 14)
WALK_AVERSION = 3.0                   # a minute on foot counts as this many minutes of driving

# ---- The rover (planning numbers) ----
ROVER_KMH = 10.0                      # on flat, firm ground
ROVER_RANGE_KM = 125.0                # default range on flat, firm ground
ROVER_SLOPE_DEG = (10, 15, 25)        # lower bound of Caution, Danger, cannot drive
ROVER_SOFT_SPEED = {0: 0.5, 1: 0.8}   # speed factor by firmness class: loose dust, soft ground
ROVER_SOFT_ENERGY = {0: 1.5, 1: 1.2}  # energy factor by firmness class (wheel slip and sinkage)
ROLLING_RESISTANCE = 0.15             # of the rover's weight, on firm regolith
MIN_STRAIN = 0.3                      # downhill still costs this share of flat-ground energy
PARK_SLOPE_DEG = 5                    # steepest ground the rover is parked on
PARK_APPROACH_DEG = 10                # steepest ground allowed in the cells around a parking spot
BOARD_MINUTES = 15                    # to get into or out of the rover (suit up, airlock)

# ---- Hazards ----
LEVELS = ["Clear", "Caution", "Danger", "Extreme"]
SLOPE_DEG = (10, 20, 30)              # on foot: lower bound of Caution, Danger, Extreme
COLD_C = (-80, -120)                  # ground colder than this is Caution, Danger (on foot)
DUST_CLASS = 0                        # firmness class that counts as loose dust

# Each hazard: key, then its description at level 1, 2 and 3 (None = it never reaches that level).
HAZARDS = [
    ("slope", ("Steep slope (10–20°)", "Very steep slope (20–30°)", "Cliff-like slope (over 30°)")),
    ("dust", ("Loose dust, may not bear weight", None, None)),
    ("cold", ("Ground colder than −80 °C", "Ground colder than −120 °C", None)),
    ("nodata", (None, None, "No elevation data")),
]
# The same hazards as the rover meets them (same order; level 3 is never driven).
ROVER_HAZARDS = [
    ("slope", ("Steep for the rover (10–15°)", "Very steep for the rover (15–25°)", None)),
    ("dust", ("Loose dust, wheels may slip", None, None)),
    ("cold", (None, None, None)),
    ("nodata", (None, None, None)),
]
LABELS = {"walk": HAZARDS, "drive": ROVER_HAZARDS}

# A metre of hazardous ground costs this many extra metres of flat travel, per hazard, by level.
SAFEST_PENALTY = (0, 20, 400, 8000)
QUICKEST_PENALTY = (0, 0, 400, 8000)  # Caution is free; the rest is only ever crossed when unavoidable
# If a route is over the rover's range, the search is repeated inside the ground the rover
# can reach, with each flat km of rover energy costing this many extra km of driving, until
# one fits. The last weight makes the drive the one that uses the least energy.
ENERGY_WEIGHTS = (0, 2, 8, 1000)
RANGE_MARGIN = 0.98                   # share of the range the repeated search plans to use

# ---- Search grid ----
MIN_CELL_M = 200                      # elevation data resolution
MAX_CELLS = 250_000                   # longer trips use larger cells to stay under this
PAD_FRACTION, PAD_MIN_M = 0.6, 4000   # how far beyond A and B a detour may go
MAX_TRIP_KM = 500                     # straight-line; beyond this the cells are too coarse to trust

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


def _walk_seconds(horizontal_m, climb_m, ground_speed):
    """Time to walk one move: surface distance over slope- and ground-adjusted speed."""
    speed = WALK_KMH / 3.6 * _tobler(climb_m / horizontal_m) * ground_speed
    return np.hypot(horizontal_m, climb_m) / speed


def _strain(gradient):
    """Rover energy per metre relative to flat firm ground, for a rise-over-run gradient in
    the direction of travel: (rolling resistance + lift against gravity) / rolling resistance.
    Downhill it falls, but never below MIN_STRAIN (the rover brakes; it does not coast)."""
    return np.maximum((1 + gradient / ROLLING_RESISTANCE) / np.sqrt(1 + gradient ** 2), MIN_STRAIN)


def _drive(horizontal_m, climb_m, ground_speed, ground_energy):
    """(seconds, flat metres of energy) to drive one move. The rover slows on a climb in
    proportion to the extra energy, and takes a descent as slowly as the same climb."""
    gradient = climb_m / horizontal_m
    metres = np.hypot(horizontal_m, climb_m)
    speed = ROVER_KMH / 3.6 * ground_speed / np.maximum(_strain(np.abs(gradient)), 1)
    return metres / speed, metres * _strain(gradient) * ground_energy


class Grid:
    """The search area as arrays of one shape, row 0 north: elevation, hazards, speeds."""

    def __init__(self, start, end, ls, local_time):
        trip_m = _distance_m(*start, *end)
        if trip_m > MAX_TRIP_KM * 1000:
            raise ValueError(f"A and B are {trip_m / 1000:.0f} km apart; routes go up to {MAX_TRIP_KM} km")
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
        dust = ground == DUST_CLASS
        slope = np.where(nodata, 0, self.slope)
        self.hazard = np.stack([                                                # on foot: level of each of HAZARDS
            np.digitize(slope, SLOPE_DEG),
            dust,
            np.digitize(-self.celsius, [-c for c in COLD_C]),
            nodata * 3,
        ]).astype(np.uint8)
        self.rover_hazard = np.stack([                                          # rover: level of each of ROVER_HAZARDS
            np.digitize(slope, ROVER_SLOPE_DEG),
            dust,
            np.zeros(self.shape),
            nodata * 3,
        ]).astype(np.uint8)
        self.level = self.hazard.max(axis=0)
        self.rover_level = self.rover_hazard.max(axis=0)

        def by_ground(factors):
            out = np.ones(self.shape, np.float32)
            for firmness_class, factor in factors.items():
                out[ground == firmness_class] = factor
            return out

        self.ground_speed = by_ground(SOFT_GROUND_SPEED)
        self.rover_speed = by_ground(ROVER_SOFT_SPEED)
        self.rover_energy = by_ground(ROVER_SOFT_ENERGY)

        # Parking: level, firm, no steep ground next to it, and safe to step out onto.
        around = ndimage.maximum_filter(np.where(nodata, 90, self.slope), size=3, mode="nearest")
        self.parking = (~nodata & ~dust & (self.slope <= PARK_SLOPE_DEG) & (around <= PARK_APPROACH_DEG)
                        & (self.level <= 1))
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
        """Every move on the grid as a dict of flat arrays: from-cell, to-cell, metres, and
        for each way of travelling its seconds and the level of each hazard (the worst
        among the cells the move touches); for the rover also its energy in flat metres."""
        rows, cols = self.shape
        index = np.arange(rows * cols, dtype=np.int32).reshape(self.shape)
        dx = self.dx[:, None] * np.ones((1, cols))
        out = []
        for dr, dc in MOVES:
            r0, r1, c0, c1 = max(0, -dr), rows - max(0, dr), max(0, -dc), cols - max(0, dc)

            def shifted(a, r=0, c=0):
                return a[..., r0 + r:r1 + r, c0 + c:c1 + c]

            crossed = _cells_crossed(dr, dc)

            def worst(a):
                return np.maximum.reduce([shifted(a, r, c) for r, c in crossed])

            def slowest(a):
                return np.minimum.reduce([shifted(a, r, c) for r, c in crossed])

            horizontal = np.hypot(dr * self.dy, dc * shifted(dx))
            climb = shifted(self.z, dr, dc) - shifted(self.z)
            drive_s, energy = _drive(horizontal, climb, slowest(self.rover_speed), worst(self.rover_energy))
            out.append(dict(
                frm=shifted(index).ravel(), to=shifted(index, dr, dc).ravel(),
                metres=np.hypot(horizontal, climb).ravel(),
                walk_s=_walk_seconds(horizontal, climb, slowest(self.ground_speed)).ravel(),
                drive_s=drive_s.ravel(), energy=energy.ravel(),
                walk_hazard=worst(self.hazard).reshape(len(HAZARDS), -1),
                drive_hazard=worst(self.rover_hazard).reshape(len(HAZARDS), -1),
            ))
        return {key: np.concatenate([part[key] for part in out], axis=-1) for key in out[0]}


class Search:
    """Least-cost trips over the grid, on three copies of it: walking before the drive (0),
    driving (1), walking after the drive (2). A trip starts at A in copy 0 and ends at B in
    copy 2. It steps from copy 0 to 1 and from 1 to 2 only at a parking spot, so the rover
    makes one continuous drive; a trip with no drive steps from 0 to 2 at B."""

    def __init__(self, grid, a, b):
        self.grid, self.n = grid, grid.z.size
        cols = grid.shape[1]
        self.a, self.b = a[0] * cols + a[1], b[0] * cols + b[1]
        self.m = grid.moves()
        self.walk_worst = self.m["walk_hazard"].max(axis=0)
        self.drive_worst = self.m["drive_hazard"].max(axis=0)
        self.parking = np.flatnonzero(grid.parking.ravel()).astype(np.int32)
        self._found = {}

    def reach(self, ceiling, cell, range_km):
        """True for each cell the rover can drive to from `cell` within RANGE_MARGIN of its range."""
        m = self.m
        drive = self.drive_worst <= min(ceiling, 2)
        graph = csr_matrix((m["energy"][drive], (m["frm"][drive], m["to"][drive])), shape=(self.n, self.n))
        return dijkstra(graph, indices=cell) <= RANGE_MARGIN * range_km * 1000

    def path(self, penalty, ceiling, energy_weight=0.0, board_at=None, reach=None):
        """Graph nodes (copy * n + cell) of the least-cost trip that stays at or under hazard
        level `ceiling`, or None if there is none. The rover never drives Extreme ground.
        With board_at and reach, the rover is boarded at that cell and stays on reach cells."""
        key = (tuple(penalty), ceiling, energy_weight)
        if reach is None and key in self._found:
            return self._found[key]
        m, n = self.m, self.n
        penalty = np.asarray(penalty, np.float32)
        walk = self.walk_worst <= ceiling
        drive = self.drive_worst <= min(ceiling, 2)
        board_cells = leave_cells = self.parking
        if reach is not None:
            drive = drive & reach[m["frm"]] & reach[m["to"]]
            board_cells = np.array([board_at], np.int32)
            leave_cells = self.parking[reach[self.parking]]

        def extra_metres(hazard, allowed):
            return m["metres"][allowed] * sum(penalty[levels[allowed]] for levels in hazard)

        walk_cost = (WALK_AVERSION * m["walk_s"][walk]
                     + extra_metres(m["walk_hazard"], walk) / (WALK_KMH / 3.6))
        drive_cost = (m["drive_s"][drive]
                      + (extra_metres(m["drive_hazard"], drive) + energy_weight * m["energy"][drive]) / (ROVER_KMH / 3.6))
        board = np.full(len(board_cells) + len(leave_cells), BOARD_MINUTES * 60.0)
        frm = np.concatenate([m["frm"][walk], n + m["frm"][drive], 2 * n + m["frm"][walk],
                              board_cells, n + leave_cells, [self.b]])
        to = np.concatenate([m["to"][walk], n + m["to"][drive], 2 * n + m["to"][walk],
                             n + board_cells, 2 * n + leave_cells, [2 * n + self.b]])
        cost = np.concatenate([walk_cost, drive_cost, walk_cost, board, [1e-6]])
        graph = csr_matrix((cost, (frm, to)), shape=(3 * n, 3 * n))
        _, before = dijkstra(graph, indices=self.a, return_predecessors=True)
        end = 2 * n + self.b
        path = None
        if before[end] >= 0:
            path = [end]
            while path[-1] != self.a:
                path.append(int(before[path[-1]]))
            path = path[::-1]
        if reach is None:
            self._found[key] = path
        return path


def _distance_m(lon0, lat0, lon1, lat1):
    p0, p1 = math.radians(lat0), math.radians(lat1)
    a = math.sin((p1 - p0) / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(math.radians(lon1 - lon0) / 2) ** 2
    return 2 * elevation.MARS_RADIUS_M * math.asin(math.sqrt(a))


def _describe(grid, path, start, end, unavoidable, penalty, range_km, max_walk_km):
    """Everything the viewer shows for one route: its line, legs, totals, hazard stretches,
    and whether it is viable.

    unavoidable[h] is the level of hazard h that no route can stay under. A hazard on this
    route is tagged unavoidable when it is exactly that level and the route was penalised
    for it, so the tagged stretches are as short as the route could make them."""
    rows, cols = grid.shape
    n = grid.z.size
    cells, modes, parking = [divmod(path[0] % n, cols)], [], []   # modes[i]: how line[i]..line[i+1] is travelled
    for before, node in zip(path, path[1:]):
        if before % n == node % n:                   # a step between copies: boarding or leaving the rover
            if 1 in (before // n, node // n):
                r, c = cells[-1]
                parking.append(dict(index=len(cells) - 1, kind="board" if node // n == 1 else "leave",
                                    slope_deg=round(float(grid.slope[r, c]), 1)))
            continue
        cells.append(divmod(node % n, cols))
        modes.append("drive" if before // n == 1 else "walk")
    line = [[float(grid.lons[c]), float(grid.lats[r])] for r, c in cells]
    for spot in parking:
        spot["at"] = line[spot["index"]]
    line[0], line[-1] = list(start), list(end)

    totals = dict(climb=0.0, descent=0.0, dose_usv=0.0, energy=0.0)
    legs = []                                        # consecutive moves travelled the same way
    stretches = []                                   # consecutive moves with the same hazards
    for i, ((r, c), (r2, c2), mode) in enumerate(zip(cells, cells[1:], modes)):
        dr, dc = r2 - r, c2 - c
        crossed = [(r + a, c + b) for a, b in _cells_crossed(dr, dc)]
        horizontal = math.hypot(dr * grid.dy, dc * grid.dx[r])
        climb = float(grid.z[r2, c2] - grid.z[r, c])
        metres = math.hypot(horizontal, climb)
        if mode == "drive":
            seconds, energy = _drive(horizontal, climb, min(grid.rover_speed[cell] for cell in crossed),
                                     max(grid.rover_energy[cell] for cell in crossed))
            totals["energy"] += float(energy)
            levels = grid.rover_hazard
        else:
            seconds = _walk_seconds(horizontal, climb, min(grid.ground_speed[cell] for cell in crossed))
            levels = grid.hazard
        seconds = float(seconds)
        totals["climb" if climb > 0 else "descent"] += abs(climb)
        totals["dose_usv"] += (grid.dose[r, c] + grid.dose[r2, c2]) / 2 * 1000 / 86400 * seconds
        if not legs or legs[-1]["mode"] != mode:
            legs.append({"mode": mode, "from": i, "to": i, "metres": 0.0, "seconds": 0.0})
        legs[-1]["to"] = i + 1
        legs[-1]["metres"] += metres
        legs[-1]["seconds"] += seconds

        hazard = np.max([levels[:, a, b] for a, b in crossed], axis=0)
        level = int(hazard.max())
        if level == 0:
            continue
        found = (mode, tuple((h, int(hazard[h])) for h in range(len(HAZARDS)) if hazard[h]))
        if stretches and stretches[-1]["to"] == i and stretches[-1]["found"] == found:
            stretch = stretches[-1]
        else:
            stretch = dict(found=found, level=level, mode=mode, start=i, to=i, distance_m=0.0, minutes=0.0)
            stretches.append(stretch)
        stretch["to"] = i + 1
        stretch["distance_m"] += metres
        stretch["minutes"] += seconds / 60

    def forced(h, lv):
        return lv == unavoidable[h] and penalty[lv] > 0

    def label(mode, h, lv):
        return LABELS[mode][h][1][lv - 1] or HAZARDS[h][1][lv - 1]

    hazards = {}                                     # the same, added up per hazard description
    for stretch in stretches:
        mode, found = stretch.pop("found")
        stretch["hazards"] = [label(mode, h, lv) for h, lv in found]
        stretch["unavoidable"] = any(forced(h, lv) for h, lv in found)
        stretch["from"] = stretch.pop("start")       # line[from] .. line[to] is the stretch
        stretch["distance_m"] = round(stretch["distance_m"])
        stretch["minutes"] = round(stretch["minutes"], 1)
        for h, lv in found:
            entry = hazards.setdefault((lv, mode, h), dict(level=lv, mode=mode, label=label(mode, h, lv),
                                                           distance_m=0, unavoidable=forced(h, lv)))
            entry["distance_m"] += stretch["distance_m"]

    def total(mode, key):
        return sum(leg[key] for leg in legs if leg["mode"] == mode)

    walk_km, drive_km = total("walk", "metres") / 1000, total("drive", "metres") / 1000
    range_used_km = totals["energy"] / 1000
    seconds = total("walk", "seconds") + total("drive", "seconds") + len(parking) * BOARD_MINUTES * 60
    longest_walk_h = max((leg["seconds"] for leg in legs if leg["mode"] == "walk"), default=0) / 3600
    worst_on_foot = max((s["level"] for s in stretches if s["mode"] == "walk"), default=0)

    reasons = []                                     # why the route cannot be done as planned
    if range_used_km > range_km:
        reasons.append(f"The drive needs the energy of {range_used_km:.0f} km of flat driving "
                       f"({drive_km:.0f} km driven, plus slopes and soft ground); the rover's range is {range_km:g} km.")
    if walk_km > max_walk_km:
        reasons.append(f"It needs {walk_km:.1f} km on foot; the walking limit is {max_walk_km:g} km.")
    if longest_walk_h > MAX_EVA_HOURS:
        reasons.append(f"One walk takes {longest_walk_h:.1f} hours, longer than one {MAX_EVA_HOURS:.0f}-hour EVA.")
    if worst_on_foot == 3:
        kinds = sorted({text for s in stretches if s["mode"] == "walk" and s["level"] == 3 for text in s["hazards"]})
        reasons.append("It crosses Extreme ground on foot: " + "; ".join(kinds) + ".")
    warnings = []
    if RECORD_WALK_KM < walk_km <= max_walk_km:
        warnings.append(f"{walk_km:.1f} km on foot is further than anyone has walked on another world "
                        f"(Apollo 14, about {RECORD_WALK_KM} km).")
    if not drive_km:
        warnings.append("The rover is not used: no drivable ground with a parking spot helps this trip.")
    if totals["dose_usv"] > radiation.DEFAULT_EVA_BUDGET_MSV * 1000:
        warnings.append(f"Radiation dose is over the {radiation.DEFAULT_EVA_BUDGET_MSV} mSv planning budget for one excursion.")

    walk_minutes, drive_minutes = round(total("walk", "seconds") / 60), round(total("drive", "seconds") / 60)
    for leg in legs:
        leg["distance_km"] = round(leg.pop("metres") / 1000, 2)
        leg["minutes"] = round(leg.pop("seconds") / 60)
    on_path = tuple(np.array(cells).T)
    return {
        "line": line,
        "legs": legs,
        "parking": parking,
        "viable": not reasons,
        "reasons": reasons,
        "distance_km": round(walk_km + drive_km, 2),
        "minutes": round(seconds / 60),
        "walk_km": round(walk_km, 2),
        "walk_minutes": walk_minutes,
        "drive_km": round(drive_km, 2),
        "drive_minutes": drive_minutes,
        "range_used_km": round(range_used_km, 1),
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


def _over_limits(route, range_km, max_walk_km):
    """How far a route is over the rover's range and the walking limit, as a share of each."""
    return (max(route["range_used_km"] / range_km - 1, 0) + max(route["walk_km"] / max_walk_km - 1, 0)
            + (0 if route["viable"] else 1e-3))


def plan(start, end, ls=90.0, local_time=12.0, range_km=ROVER_RANGE_KM, max_walk_km=MAX_WALK_KM):
    """The safest and the quickest trip between two [lon, lat] points, by rover and on foot.

    ls           season, solar longitude in degrees (see temperature.py)
    local_time   departure, local true solar time in hours; sets how cold the ground is
    range_km     how far the rover drives on flat firm ground
    max_walk_km  the most walking allowed in the whole trip

    Returns a dict the viewer draws directly; see _describe for what each route holds.
    Raises ValueError if the points are too far apart or the trip cannot be gridded.
    """
    start, end = [float(v) for v in start], [float(v) for v in end]
    range_km, max_walk_km = float(range_km), float(max_walk_km)
    if not (range_km > 0 and max_walk_km > 0):
        raise ValueError("the rover's range and the walking limit must be above zero")
    grid = Grid(start, end, ls, local_time)
    a, b = grid.cell(*start), grid.cell(*end)
    if a == b:
        raise ValueError(f"A and B are in the same {grid.cell_m:.0f} m cell; pick points further apart")
    search = Search(grid, a, b)

    # What no route can avoid. A cell counts at its easier level, on foot or by rover; this
    # is a lower bound (the rover also needs parking spots), so the level is then raised
    # until a trip exists.
    easier = np.minimum(grid.hazard, np.where(grid.rover_hazard == 3, grid.hazard, grid.rover_hazard))
    unavoidable = [grid.lowest_connecting_level(levels, a, b) for levels in easier]
    floor = grid.lowest_connecting_level(easier.max(axis=0), a, b)
    while search.path(SAFEST_PENALTY, floor) is None:
        floor += 1
    if floor > max(unavoidable):          # avoidable one at a time, but not all at once
        unavoidable = [floor] * len(HAZARDS)

    def best(penalty, ceiling):
        """The route for one penalty table. If it is over the rover's range, also the route
        that parks before the range runs out and walks on; then whichever is closer to the limits."""
        def describe(path):
            return _describe(grid, path, start, end, unavoidable, penalty, range_km, max_walk_km)

        path = search.path(penalty, ceiling)
        route = describe(path)
        if route["range_used_km"] <= range_km:
            return route
        board_at = next(node % search.n for node in path if node // search.n == 1)
        reach = search.reach(ceiling, board_at, range_km)
        short = None                                 # the drive kept within range
        for weight in ENERGY_WEIGHTS:
            path = search.path(penalty, ceiling, weight, board_at, reach)
            short = path and describe(path)
            if not short or short["range_used_km"] <= range_km:
                break
        if not short or short["range_used_km"] > range_km:
            return route
        if _over_limits(short, range_km, max_walk_km) <= _over_limits(route, range_km, max_walk_km):
            return short
        route["reasons"].append(f"Parking where the range runs out would leave {short['walk_km']:.0f} km on foot; "
                                f"the walking limit is {max_walk_km:g} km.")
        return route

    routes = {"safest": best(SAFEST_PENALTY, floor), "quickest": best(QUICKEST_PENALTY, max(floor, 1))}
    safest, quickest = routes["safest"], routes["quickest"]
    over = [_over_limits(route, range_km, max_walk_km) for route in (safest, quickest)]
    if over[1] > over[0] or (over[1] == over[0] and quickest["minutes"] > safest["minutes"]):
        # Happens when Danger is unavoidable or the limits are tight: then nothing quicker
        # is acceptable, and the safest route is both.
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
    viable = safest["viable"] or quickest["viable"]
    return {
        "start": start, "end": end,
        "straight_km": round(_distance_m(*start, *end) / 1000, 2),
        "cell_m": round(grid.cell_m),
        "search_box": list(grid.box),
        "ls": ls, "local_time": local_time,
        "range_km": range_km, "max_walk_km": max_walk_km,
        "unavoidable_level": floor,
        "verdict": verdict,
        "viable": viable,
        "viability": ("A viable route exists." if viable else
                      "No viable route was found. The routes shown are the closest to the limits."),
        "routes": routes,
    }


def legend():
    """Hazard levels and the numbers behind the routes, for the viewer's panel."""
    return {
        "levels": [{"level": i, "label": label} for i, label in enumerate(LEVELS)],
        "walk_kmh": WALK_KMH, "max_eva_hours": MAX_EVA_HOURS,
        "max_walk_km": MAX_WALK_KM, "record_walk_km": RECORD_WALK_KM,
        "rover_kmh": ROVER_KMH, "rover_range_km": ROVER_RANGE_KM,
        "slope_deg": SLOPE_DEG, "rover_slope_deg": ROVER_SLOPE_DEG, "cold_c": COLD_C,
        "park_slope_deg": PARK_SLOPE_DEG, "board_minutes": BOARD_MINUTES,
        "max_trip_km": MAX_TRIP_KM,
        "note": "Planning numbers chosen by the team, not NASA limits. Terrain is seen at "
                f"{MIN_CELL_M} m or coarser, ground firmness and temperature at 3 km.",
    }


if __name__ == "__main__":
    result = plan(radiation.RAD_SITE, (137.38, -4.72))        # Bradbury Landing to the foot of Mount Sharp
    print(result["verdict"], result["viability"], f"({result['straight_km']} km straight, {result['cell_m']} m cells)")
    for name, route in result["routes"].items():
        print(f"  {name:8s} {route['distance_km']:6.2f} km  {route['minutes']:4d} min  "
              f"drive {route['drive_km']} km (range used {route['range_used_km']} km)  walk {route['walk_km']} km  "
              f"worst: {LEVELS[route['worst_level']]}")
        for h in route["hazards"]:
            print(f"           {LEVELS[h['level']]} ({h['mode']}): {h['label']}, {h['distance_m']} m"
                  + (" (unavoidable)" if h["unavoidable"] else ""))
        for reason in route["reasons"] + route["warnings"]:
            print("           !", reason)
