# The viewer and its server as one container, for Google Cloud Run (see DEPLOY.md).
#
# In the image: the code, the web pages, the data that is in git, and the two small data
# files that are not (thermal inertia, 52 MB; the Gale radiation cache, 2 MB).
# Not in the image: the elevation file (3.8 GB). The server reads it from a storage bucket,
# named by MARS_DEM when the service is deployed.

FROM python:3.14-slim

# libexpat1: a system library rasterio's GDAL needs that the slim image leaves out.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY web/ web/
COPY ice_data/ ice_data/
COPY temperature_data/ temperature_data/
COPY data/thermal_inertia/ data/thermal_inertia/
COPY data/radiation/ data/radiation/

# How GDAL reads the elevation file from the bucket:
#   CPL_MACHINE_IS_GCE              sign in as the Cloud Run service, with no key file
#   GDAL_DISABLE_READDIR_ON_OPEN    do not list the bucket when opening the file
#   GDAL_HTTP_MULTIRANGE / MERGE    fetch the blocks of one read together
#   VSI_CACHE, GDAL_CACHEMAX (MB)   keep what was read in memory, so a place is fetched once
ENV CPL_MACHINE_IS_GCE=YES \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif \
    GDAL_HTTP_MULTIRANGE=YES \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES \
    VSI_CACHE=TRUE \
    GDAL_CACHEMAX=512 \
    PYTHONUNBUFFERED=1

# Cloud Run says which port to listen on in PORT. One process: its threads share the
# tiles it has drawn and the one-route-at-a-time lock (server.py).
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
