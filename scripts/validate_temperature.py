"""Checks the temperature model against Curiosity's REMS ground temperature sensor.

For each season (15 degrees of Ls) it compares the daily low and high that Curiosity
measured in Gale crater with what temperature.py predicts along the rover's traverse.

Run:  .venv/bin/python scripts/validate_temperature.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import temperature  # noqa: E402


def main():
    rems = json.loads((ROOT / "web/data/rems_ground_temperature.json").read_text())["bins"]
    track = json.loads((ROOT / "web/data/MSL_3420.geojson").read_text())["features"][::200]
    points = np.array([f["geometry"]["coordinates"][:2] for f in track])
    ground = [temperature.read_ground(lon - 1e-3, lat - 1e-3, lon + 1e-3, lat + 1e-3, shape=(1, 1)) for lon, lat in points]
    inertia = np.array([g[0][0, 0] for g in ground])[None, :]
    albedo = np.array([g[1][0, 0] for g in ground])[None, :]
    lat = [float(points[:, 1].mean())]
    print(f"{len(points)} traverse points, thermal inertia median {np.median(inertia):.0f}, albedo {np.median(albedo):.2f}")
    print("  Ls    low: REMS model diff    high: REMS model diff   (kelvin)")
    diffs = []
    for b in rems:
        ls = (b["ls_from"] + b["ls_to"]) / 2
        low = float(np.mean(temperature._lookup(temperature._season_table(ls, stat="min"), lat, inertia, albedo)))
        high = float(np.mean(temperature._lookup(temperature._season_table(ls, stat="max"), lat, inertia, albedo)))
        diffs.append((low - b["ground_min"], high - b["ground_max"]))
        print(f"{ls:5.1f}        {b['ground_min']:5.0f} {low:5.0f} {diffs[-1][0]:+5.1f}"
              f"          {b['ground_max']:5.0f} {high:5.0f} {diffs[-1][1]:+5.1f}")
    d = np.array(diffs)
    print(f"daily low:  mean difference {d[:, 0].mean():+.1f} K, RMS {np.sqrt((d[:, 0]**2).mean()):.1f} K")
    print(f"daily high: mean difference {d[:, 1].mean():+.1f} K, RMS {np.sqrt((d[:, 1]**2).mean()):.1f} K")


if __name__ == "__main__":
    main()
