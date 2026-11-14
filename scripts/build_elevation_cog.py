"""Writes a faster copy of the 15 GB elevation file, next to the original.

The original (data/elevation/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) is stored in
strips as wide as the planet, so reading a small window has to step through whole rows.
The copy is a Cloud-Optimized GeoTIFF: 512 px blocks, DEFLATE compression with a
predictor, BIGTIFF, with the reduced copies (overviews) inside the file. The heights are
the same numbers; the reduced copies are taken from the original's .ovr file, so
zoomed-out reads give the same numbers too.

elevation.py uses the copy when it exists and the original when it does not.

Run:  python scripts/build_elevation_cog.py        (3 to 15 minutes, needs 4 GB free)
"""
import sys
import time
from pathlib import Path

import rasterio
from rasterio.shutil import copy

sys.path.insert(0, str(Path(__file__).parent.parent))
import elevation

if __name__ == "__main__":
    source, target = elevation.SOURCE_DEM_PATH, elevation.COG_DEM_PATH
    part = target.with_suffix(".part.tif")      # renamed at the end, so a half-written file is never used
    start = time.time()
    with rasterio.Env(GDAL_CACHEMAX=2048):
        copy(source, part, driver="COG", COMPRESS="DEFLATE", PREDICTOR="2", BLOCKSIZE="512",
             BIGTIFF="YES", OVERVIEWS="FORCE_USE_EXISTING", NUM_THREADS="ALL_CPUS")
    part.replace(target)
    print(f"{target.name}: {target.stat().st_size / 1e9:.2f} GB in {(time.time() - start) / 60:.1f} minutes "
          f"(original {source.stat().st_size / 1e9:.2f} GB + {source.with_name(source.name + '.ovr').stat().st_size / 1e9:.2f} GB .ovr)")
