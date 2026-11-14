"""Builds the two ground-property maps temperature.py reads (already committed in temperature_data/):

  mars_thermal_inertia_16ppd.tif   from the 24 THEMIS quantitative thermal inertia tiles (100 m/px)
  mars_albedo_8ppd.tif             from the TES global bolometric albedo map (7.4 km/px)

You only need to run this to rebuild them. It downloads ~55 GB, one tile at a time, into
data/temperature/ and deletes each tile after reducing it (pass --keep to keep them: the
tiles you keep give temperature.py 100 m detail there).

Run:  .venv/bin/python scripts/build_temperature_inputs.py [--keep]
To fetch single tiles for 100 m detail instead, see DATA_SOURCES.md.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

ROOT = Path(__file__).parent.parent
OUT = ROOT / "temperature_data"
WORK = ROOT / "data/temperature"
THEMIS_URL = ("https://asc-astropedia.s3.us-west-2.amazonaws.com/Mars/Odyssey/THEMIS-Global-Thermal-Inertia-Mosaic/"
              "Quantitative-32-Bit/ancillary/THEMIS_TI_Mosaic_Quant_{name}_100mpp.tif")
ALBEDO_URL = "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif"
TILES = [f"{lat}{lon:03d}E" for lat in ("30N", "00N", "30S", "60S") for lon in range(0, 360, 60)]
PPD = 16
M_PER_DEG = np.pi * 3396190.0 / 180
POLAR_FILL = 200.0        # THEMIS inertia stops at 60 deg; typical high-latitude value used beyond


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sSL", "--retry", "5", "-C", "-", "-o", str(path), url], check=True)


def reduce_tile(name, keep):
    """Sum of log(inertia) and count of valid 100 m pixels in each 1/16 degree cell of one tile."""
    out = WORK / "reduced" / f"{name}.npz"
    if out.exists():
        return out
    tif = WORK / f"THEMIS_TI_Mosaic_Quant_{name}_100mpp.tif"
    download(THEMIS_URL.format(name=name), tif)
    with rasterio.open(tif) as d:
        t = d.transform
        lon0, lat1 = round(t.c / M_PER_DEG), round(t.f / M_PER_DEG)      # west edge (0..360 E), north edge
        col_cell = np.clip(np.floor(((t.c + (np.arange(d.width) + .5) * t.a) / M_PER_DEG - lon0) * PPD).astype(int),
                           0, 60 * PPD - 1)
        row_cell = np.clip(np.floor((lat1 - (t.f + (np.arange(d.height) + .5) * t.e) / M_PER_DEG) * PPD).astype(int),
                           0, 30 * PPD - 1)
        col_start = np.searchsorted(col_cell, np.arange(60 * PPD))
        total = np.zeros((30 * PPD, 60 * PPD))
        count = np.zeros_like(total)
        for r in range(30 * PPD):
            rows = np.nonzero(row_cell == r)[0]
            if not len(rows):
                continue
            a = d.read(1, window=Window(0, rows[0], d.width, len(rows)))
            ok = (a > 5) & (a < 5000)
            logs = np.where(ok, np.log(np.where(ok, a, 1)), 0)
            total[r] = np.add.reduceat(logs.sum(0), col_start)
            count[r] = np.add.reduceat(ok.sum(0), col_start)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, s=total.astype(np.float32), n=count.astype(np.int32), lon0=lon0, lat1=lat1)
    if not keep:
        tif.unlink()
    return out


def fill_gaps(total, count):
    """Geometric-mean inertia per cell; empty cells take the mean of ever larger blocks around them."""
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(count > 0, total / count, np.nan)
        factor = 1
        while np.isnan(result).any() and factor < total.shape[0]:
            factor *= 2
            rows, cols = total.shape[0] // factor, total.shape[1] // factor
            s = total[:rows * factor, :cols * factor].reshape(rows, factor, cols, factor).sum((1, 3))
            n = count[:rows * factor, :cols * factor].reshape(rows, factor, cols, factor).sum((1, 3))
            coarse = np.repeat(np.repeat(np.where(n > 0, s / n, np.nan), factor, 0), factor, 1)
            part = result[:rows * factor, :cols * factor]
            part[np.isnan(part)] = coarse[np.isnan(part)]
    return np.exp(result)


def write(path, data, ppd, dtype, **tags):
    profile = dict(driver="GTiff", dtype=dtype, count=data.shape[0], height=data.shape[1], width=data.shape[2],
                   transform=from_origin(-180, 90, 1 / ppd, 1 / ppd), compress="deflate", predictor=2, tiled=True)
    with rasterio.open(path, "w", **profile) as d:
        d.write(data.astype(dtype))
        d.update_tags(**tags)
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")


def main():
    keep = "--keep" in sys.argv
    OUT.mkdir(exist_ok=True)

    # Thermal inertia: lon -180..180, lat 90..-90; THEMIS covers 60S..60N.
    total = np.zeros((120 * PPD, 360 * PPD))
    count = np.zeros_like(total)
    for name in TILES:
        z = np.load(reduce_tile(name, keep))
        r0 = (60 - int(z["lat1"])) * PPD
        c0 = ((int(z["lon0"]) + 180) % 360) * PPD                 # 0..360 E to -180..180
        total[r0:r0 + 30 * PPD, c0:c0 + 60 * PPD] = z["s"]
        count[r0:r0 + 30 * PPD, c0:c0 + 60 * PPD] = z["n"]
    inertia = np.full((180 * PPD, 360 * PPD), POLAR_FILL)
    inertia[30 * PPD:150 * PPD] = fill_gaps(total, count)
    measured = np.zeros(inertia.shape)
    measured[30 * PPD:150 * PPD] = count > 0
    write(OUT / "mars_thermal_inertia_16ppd.tif", np.stack([np.round(inertia), measured]), PPD, "uint16",
          band_1="thermal inertia, J m-2 K-1 s-1/2 (THEMIS, geometric mean of 100 m pixels; gaps filled)",
          band_2="1 where THEMIS measured the cell, 0 where filled")

    # Albedo: already lon -180..180 at 8 px/deg; stored as albedo x 10000.
    src = WORK / "Mars_MGS_TES_Albedo_mosaic_global_7410m.tif"
    if not src.exists():
        download(ALBEDO_URL, src)
    with rasterio.open(src) as d:
        albedo = d.read(1)
    write(OUT / "mars_albedo_8ppd.tif", np.round(albedo * 10000)[None], 8, "uint16",
          band_1="TES bolometric albedo x 10000")


if __name__ == "__main__":
    main()
