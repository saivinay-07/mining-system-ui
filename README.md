# Smart Vehicle Entry & Exit — Dataset Manager

A local web application for manually collecting and organizing vehicle and number plate images. It previews public image URLs, validates downloaded files, checks duplicates, stores unique images in the fixed `dataset/` tree and keeps metadata in SQLite.

## Features

- Responsive dashboard and navigation for desktop and mobile.
- URL preview with dimensions, format, size and server-side duplicate checks.
- Category-aware forms that only allow the approved folder combinations.
- Actual image download and local storage with generated filenames.
- Duplicate detection by normalized URL, SHA-256 and conservative 64-bit average perceptual hash (up to 3 differing bits).
- Dataset gallery with search, category filters, sort, pagination, metadata view and confirmed deletion.
- Expandable fixed folder tree with live counts, collection statistics and duplicate attempt history.
- SQLite persistence and server-side safeguards for private network URLs, redirects, payload limits and path traversal.

## Technology

- Python 3.10+
- Flask for the local HTTP API and static application serving.
- SQLite for image metadata and duplicate attempts.
- Pillow for validating image content and calculating image dimensions and visual hashes.
- HTML, CSS and JavaScript for the responsive browser interface.

## Install and run

From the project root, create and activate a virtual environment, then install dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The server binds to localhost by default. Set `HOST` and `PORT` to override the bind address and port. Set `DATASET_MAX_IMAGE_BYTES` to change the per-image download limit (default 15 MiB).

## Deploy to Render

The repository root must contain `requirements.txt`, `app.py`, `wsgi.py` and the `web/` directory. In the Render service settings, set the root directory to the repository root, then use:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT wsgi:app`
- Health check path: `/api/health`

The `.python-version` file selects Python 3.13. Render deploys the branch and commit configured in the service, so these files must be pushed to that branch (the failing deployment log was built from an older commit that did not contain `requirements.txt`).

For persistent collection storage, attach a Render persistent disk mounted at `/var/data` and set these environment variables:

```text
DATASET_ROOT=/var/data/dataset
DATASET_DB_PATH=/var/data/dataset_manager.sqlite3
```

Both the database and collected images must be under the mounted path or they can be lost when the service is replaced. Render persistent disks are configured in the service dashboard and incur plan/storage costs; choose and confirm the suitable plan there. Keep one service instance when using a disk because the disk is attached to a single instance.

## Data locations

- Dataset images: `dataset/`
- SQLite database: `dataset_manager.sqlite3`
- Web interface: `web/`

On first startup, the server creates any missing approved directories. It does not create extra dataset categories. Existing files are left in place; the app only counts records it manages in its database.

The only destinations are:

- `number_plates/{bright_sunlight,clear,cloudy,dirty,dust_haze,far_distance,medium_distance,night,rain,slightly_blurred}/`
- `others/not_lorry/`
- `vehicles/{diagonal,front,multi_vehicles,rear,side}/{blurred,bright_sunlight,clear,cloudy,dust_haze,far_distance,medium_distance,near,night,rain}/`

## Collect an image

1. Open **Add Image** and paste a direct public HTTP or HTTPS image URL.
2. Click **Preview**. The server retrieves and validates the image, displays metadata and checks duplicates.
3. Select the dataset type and any required view and condition values.
4. Confirm the displayed destination and click **Submit & save**.
5. The app downloads the file again, repeats duplicate checks, saves the image and commits its metadata. A failed save removes its incomplete file.

Google search/result pages are not direct image URLs. URLs resolving to localhost, private, reserved or link-local network addresses are rejected. Redirect destinations are checked individually. Only supported image content is accepted; URL extensions and content type headers are not trusted. The default maximum download size is 15 MiB.

## Duplicate checks

The server first compares a normalized URL, then exact file SHA-256, then compares a simple average hash. Visual matches are blocked only within a narrow Hamming distance of 3 out of 64 bits. The duplicate image is never inserted as a new image record; attempted matches are written to `duplicate_attempts` and shown on **Duplicate Check**. SQLite unique constraints protect normalized URLs and exact hashes; a server lock serializes save operations in a running app process.

## Database and storage behavior

The SQLite database is created automatically at startup. Each saved image record references its path inside `dataset/` and stores type, view, condition, file hash, visual hash, dimensions, size, format, source URL and creation time. Deleting from the gallery removes the managed image file and its record. Duplicate-attempt history for a deleted image is removed by the database foreign-key cascade.

Dashboard, folder counts and statistics use real managed records. The original `Truck/` images are not automatically imported because the repository does not provide reliable per-image labels for the required category tree.

## Troubleshooting

- **Could not retrieve image:** check that the URL is public, reachable from the machine running the app and does not require browser cookies or sign-in.
- **Unsupported image URL:** use a direct file URL rather than a search results or landing page URL.
- **Image exceeds the limit:** configure `DATASET_MAX_IMAGE_BYTES` and restart the server.
- **Port already in use:** set `PORT` to an available port, for example `$env:PORT=5001` before running `python app.py`.
- **Image missing after a manual file operation:** the record remains in SQLite; remove the record through the UI if the file is no longer available, or restore its file at the recorded path.
- **Reset local records:** stop the server before intentionally removing `dataset_manager.sqlite3` and its SQLite `-wal` / `-shm` files. Dataset image files are separate and are not removed by deleting the database.

## Development checks

```powershell
python -m py_compile app.py
node --check web/app.js
```
