"""Times every tile endpoint and records response sizes, to compare before and after a change.

Starts its own server on a spare port, so the first call to each tile is a cold draw, asks
for each tile twice, and saves the numbers under data/measurements/<label>.json (not in git).
Every run prints a table of all saved labels side by side.

Run:  python scripts/measure_tiles.py baseline
      python scripts/measure_tiles.py step1
      python scripts/measure_tiles.py            (only prints the saved runs)

Tiles measured: every tile of levels 0 to 2 (the whole planet), and the tile holding the
middle of Gale crater (lon 137.4, lat -4.7) at levels 5, 7 and 9.
Sizes are bytes on the wire: a compressed response counts at its compressed size.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "data/measurements"
PORT = 8123
GALE = (137.4, -4.7)

# name -> address of one tile; {t} is level/row/col.
ENDPOINTS = {
    "elevation": "/elevation/{t}",
    "contours": "/contours/{t}.png",
    "firmness": "/firmness/{t}.png",
    "ice": "/ice/{t}.png",
    "radiation dose": "/radiation/tiles/dose/{t}.png",
    "radiation shelter": "/radiation/tiles/shelter/{t}.png",
    "temperature": "/temperature/{t}.png?ls=90&local_time=14&stat=",
}


def tile_groups():
    """Group name -> list of 'level/row/col'."""
    planet = [f"{level}/{row}/{col}" for level in range(3)
              for row in range(2**level) for col in range(2 * 2**level)]
    groups = {"planet L0-2": planet}
    for level in (5, 7, 9):
        span = 180 / 2**level
        groups[f"Gale L{level}"] = [f"{level}/{int((90 - GALE[1]) // span)}/{int((GALE[0] + 180) // span)}"]
    return groups


def fetch(path):
    """(seconds, bytes on the wire) for one request."""
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers={"Accept-Encoding": "gzip"})
    start = time.perf_counter()
    with urllib.request.urlopen(request) as response:
        body = response.read()                    # urllib does not decompress, so this is the wire size
    return time.perf_counter() - start, len(body)


def measure():
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(PORT),
                               "--log-level", "warning"], cwd=ROOT)
    try:
        for _ in range(120):                      # wait for the server to answer
            try:
                fetch("/firmness/legend")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        results = {}
        for name, address in ENDPOINTS.items():
            for group, tiles in tile_groups().items():
                first, again, size = [], [], []
                for t in tiles:
                    seconds, n = fetch(address.format(t=t))
                    first.append(seconds)
                    size.append(n)
                    again.append(fetch(address.format(t=t))[0])
                results[f"{name} | {group}"] = {
                    "first_ms": 1000 * sum(first) / len(first),
                    "repeat_ms": 1000 * sum(again) / len(again),
                    "bytes": sum(size) / len(size),
                }
                print(f"  {name} | {group}", flush=True)
        return results
    finally:
        server.terminate()
        server.wait()


def table():
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(OUT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)}
    keys = list(dict.fromkeys(k for run in runs.values() for k in run))
    print("\nMean per tile: first draw ms / repeat ms / bytes")
    print(f"{'':34}" + "".join(f"{label:>26}" for label in runs))
    for key in keys:
        cells = []
        for run in runs.values():
            r = run.get(key)
            cells.append(f"{r['first_ms']:7.1f} /{r['repeat_ms']:6.2f} /{r['bytes']:8.0f}" if r else "-")
        print(f"{key:34}" + "".join(f"{c:>26}" for c in cells))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{sys.argv[1]}.json").write_text(json.dumps(measure(), indent=1))
    table()
