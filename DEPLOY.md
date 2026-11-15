# Putting the app on the web (Google Cloud Run)

The app runs as one container on Google Cloud Run: `server.py` serves the pages in `web/`
and draws the tiles and routes. Cloud Run is what Google AI Studio's "Publish" button deploys
to; AI Studio itself builds React and Node.js apps and cannot run this Python server.

These steps were run once, on 2026-11-14, and produced a working service: the page, every
tile layer and routes of 9, 100 and 470 km all answered. The settings come from trial runs
on a laptop (see "Why these settings").

## What goes where

| What | Size | Where it lives |
|---|---|---|
| Code, `web/`, `ice_data/`, `temperature_data/` | 60 MB | In the container image (from git) |
| `data/thermal_inertia/`, `data/radiation/` | 54 MB | In the container image (from your disk; not in git) |
| Elevation, the tiled copy `..._v2_cog.tif` | 3.8 GB | In a Cloud Storage bucket, read over the network |

The original elevation file (11.4 GB plus a 3.8 GB `.ovr`) is **not** uploaded. Only the
tiled copy works over a network.

## Before you start

- A Google Cloud project with billing switched on, and the `gcloud` command-line tool
  installed and signed in (`gcloud auth login`, `gcloud config set project YOUR_PROJECT`).
- On your disk: `data/thermal_inertia/`, `data/radiation/`, and the tiled elevation copy.
  If `data/elevation/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif` is not there, make it
  (about 15 minutes):

```bash
python scripts/build_elevation_cog.py
```

Replace `YOUR_PROJECT` and `YOUR_BUCKET` below. Bucket names are global, so pick something
unlikely to be taken, for example `YOUR_PROJECT-mars-data`. Run the commands from the
project folder. On Windows use PowerShell, not Git Bash: Git Bash rewrites the `/vsigs/...`
value in step 4 into a Windows path.

## Steps

1. Switch on the services (once per project):

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com
```

2. Make a bucket in the same region the app will run in, and upload the elevation file
   (once; 3.8 GB):

```bash
gcloud storage buckets create gs://YOUR_BUCKET --location=us-central1 --uniform-bucket-level-access
```

```bash
gcloud storage cp data/elevation/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif gs://YOUR_BUCKET/
```

3. Let the app read the bucket. Cloud Run runs as the project's default compute service
   account unless you choose another; this prints its name:

```bash
gcloud iam service-accounts list --filter="email~compute@developer" --format="value(email)"
```

```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET --member="serviceAccount:THE_EMAIL_FROM_ABOVE" --role="roles/storage.objectViewer"
```

   In a new project the same account also builds the container, and needs the "Cloud Run
   builder" role for that. Without it step 4 fails with "does not have storage.objects.get
   access":

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT --member="serviceAccount:THE_EMAIL_FROM_ABOVE" --role="roles/run.builder" --condition=None
```

4. Build and deploy. This uploads the folder (what `.gcloudignore` lets through), builds
   the `Dockerfile` in Google Cloud, and starts the service. Run the same command again to
   deploy a new version.

```bash
gcloud run deploy mars-map --source . --region us-central1 --allow-unauthenticated --execution-environment gen2 --memory 4Gi --cpu 2 --concurrency 40 --min-instances 0 --max-instances 2 --timeout 120 --cpu-boost --set-env-vars "MARS_DEM=/vsigs/YOUR_BUCKET/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif"
```

5. Check it. The command prints the app's address. Open it, switch on "Contour Lines" in
   the Layers panel, and plan a route in Gale crater. Contours and routes are the two things
   that read the elevation file, so if both work, the bucket is being read.

   Reading the bucket with `/vsigs/` worked on the first deployment, so the rest of this
   step is only for when it does not. If the page loads but contours and routes fail, the
   server could not read the bucket.
   Look at the reason (`gcloud run services logs read mars-map --region us-central1 --limit 50`).
   If it is a sign-in or permission error and step 3 was done, use the other way of reading
   the bucket: attach it as a folder. Run the deploy command again with
   `MARS_DEM=/mnt/mars/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif` and these two flags added:

```
--add-volume name=mars,type=cloud-storage,bucket=YOUR_BUCKET,readonly=true --add-volume-mount volume=mars,mount-path=/mnt/mars
```

## Why these settings

All measured on a laptop with the scripts' own data; see the notes for what was not measured.

- **Memory, 4 GiB.** Planning a route peaks at about 1.1 GB whatever the trip length (9 km:
  0.3 GB; 50 km and up, to the 500 km limit: 1.1 GB), because the search grid is capped at
  250,000 cells. `server.py` plans one route at a time, so two people asking together queue
  instead of doubling that. On top come up to 0.5 GB of elevation blocks kept in memory
  (`GDAL_CACHEMAX`), up to 0.3 GB of drawn tiles, and the idle server (0.1 GB): about 2 GB
  in the worst case. 2 GiB would be too tight; 4 GiB leaves room. Memory is the small part
  of the bill (see below), so the headroom costs little.
- **The tiled elevation copy.** Read over a network with 30 ms per request, one mid-zoom
  contour tile took 129 requests and 349 MB from the original file (28 s), and 4 requests
  and 1.1 MB from the tiled copy (0.1 s). The grid for a 100 km route: 361 MB against 1.8 MB.
  The tiled copy is also a quarter of the size to store.
- **Read with GDAL, not as a mounted folder.** `MARS_DEM=/vsigs/...` makes GDAL fetch the
  blocks itself, several per request, and keep them in memory. That is the way that was
  measured. The mounted folder (step 5) is the fallback; it was not measured and is likely
  slower, one request per block.
- **Scale to zero, at most 2 instances.** `--min-instances 0` means nothing runs, and
  nothing is billed for running, while nobody is using the app. The first visit after a
  quiet spell waits a few seconds for a start. `--max-instances 2` caps what a burst of
  traffic can cost.
- **2 CPUs, 40 requests at a time.** A page asks for many tiles at once and each is drawn
  in Python; the second CPU keeps tiles coming while a route is being planned.

## What it costs

Check Google's pricing pages before relying on these; the figures are from memory of the
published rates, not confirmed while writing this.

- Cloud Run bills the time an instance spends handling requests: roughly 2.4 cents per CPU
  for 1,000 seconds and 0.25 cents per GiB for 1,000 seconds. With 2 CPUs and 4 GiB that is
  about 21 cents per hour of active use, and there is a monthly free allowance. Idle, scaled
  to zero, it costs nothing.
- The bucket: about 2 cents per GB per month, so under 10 cents a month for 3.8 GB. Reads
  from Cloud Run in the same region carry no transfer charge.
- The container image sits in Artifact Registry: about 10 cents per GB per month, and the
  image is a few hundred MB.
- Set a budget alert in the Google Cloud console (Billing, Budgets and alerts) so a mistake
  cannot run up a bill unnoticed.

## Not measured

- Memory on Cloud Run itself. The 1.1 GB is the route planner's peak on Windows; Linux
  should be close but may differ. On the first deployment a 470 km route answered in 4 s
  and nothing ran out of memory, but the peak was not read off the service's metrics.
- How it behaves with many visitors at once. It was tested by one person.

To try the container on your own machine before deploying, start Docker and run:

```bash
docker build -t mars-map .
```

```bash
docker run --rm -p 8080:8080 -m 4g -v "%cd%/data/elevation:/dem:ro" -e MARS_DEM=/dem/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2_cog.tif mars-map
```

(In PowerShell write `${PWD}` in place of `%cd%`.) Then open http://localhost:8080.

## Optional: tiles drawn ahead of time

`scripts/build_static_tiles.py` draws the layers that never change into `data/tiles/`. They
are not in the image. If the app feels slow on those layers, that folder can be added to the
image (one `COPY` line in the `Dockerfile`, one line in `.dockerignore` and `.gcloudignore`).

## Spending cap

Google Cloud has no setting that stops spending at an amount: a budget only sends alerts.
The cap here is a small function (`deploy/billing_cap/main.py`) that receives the budget's
messages and, when the month's cost reaches the budget, disconnects the project from its
billing account. Know what that means before relying on it:

- When it fires, everything in the project stops, the app included, until someone links
  billing again by hand (console: Billing, Account management).
- It is not exact. Cost figures reach the budget hours late, so a month can end over the amount.
- If billing stays off, Google may in time delete the project's resources, the bucket
  included. The elevation file can be uploaded again (step 2).

Setting it up (run once; `BILLING_ACCOUNT` is the ID shown by `gcloud billing accounts list`,
and the budget itself is made in the console under Billing, Budgets and alerts):

```bash
gcloud services enable cloudfunctions.googleapis.com pubsub.googleapis.com eventarc.googleapis.com cloudbilling.googleapis.com billingbudgets.googleapis.com
```

```bash
gcloud pubsub topics create billing-budget-alerts
```

```bash
gcloud iam service-accounts create billing-cap --display-name="Spending cap: turns billing off at the budget"
```

The function's account may unlink billing from the project, and read the project:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT --member="serviceAccount:billing-cap@YOUR_PROJECT.iam.gserviceaccount.com" --role="roles/billing.projectManager" --condition=None
```

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT --member="serviceAccount:billing-cap@YOUR_PROJECT.iam.gserviceaccount.com" --role="roles/browser" --condition=None
```

Deploy the function. If this fails with a "serviceUsageConsumer" error straight after
enabling the services, wait two minutes and run it again:

```bash
gcloud functions deploy stop-billing --gen2 --runtime python312 --region us-central1 --source deploy/billing_cap --entry-point stop_billing --trigger-topic billing-budget-alerts --service-account billing-cap@YOUR_PROJECT.iam.gserviceaccount.com --set-env-vars TARGET_PROJECT=YOUR_PROJECT --max-instances 1 --memory 256Mi
```

Let the topic's messages reach the function, and send the budget's messages to the topic:

```bash
gcloud run services add-iam-policy-binding stop-billing --region us-central1 --member="serviceAccount:billing-cap@YOUR_PROJECT.iam.gserviceaccount.com" --role="roles/run.invoker"
```

```bash
gcloud billing budgets list --billing-account=BILLING_ACCOUNT --format="value(name,displayName)"
```

```bash
gcloud billing budgets update THE_BUDGET_NAME_FROM_ABOVE --notifications-rule-pubsub-topic=projects/YOUR_PROJECT/topics/billing-budget-alerts
```

Testing it without switching anything off: a message marked `dryRun` makes the function
say what it would do. Real budget messages never carry that mark. (Shown for PowerShell.)

```bash
gcloud pubsub topics publish billing-budget-alerts --message='{\"costAmount\": 25, \"budgetAmount\": 20, \"dryRun\": true}'
```

```bash
gcloud functions logs read stop-billing --gen2 --region us-central1 --limit 5
```

The log should show "DRY RUN: cost 25 has reached the budget of 20; would take billing off".
The dry run exercises everything except the final call that unlinks billing, which has not
been run for real.

To remove the cap: `gcloud functions delete stop-billing --gen2 --region us-central1`.
