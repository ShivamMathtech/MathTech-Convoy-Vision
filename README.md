# MathTech Convoy Vision

**Vehicle detection, instance segmentation, tracking and visual analytics**  
Developed by **Shivam Singh, Founder of MathTech**  
**I HAVE NO LIMITATION**

A complete, self-hosted, single-node application based on your dashboard reference. It includes the backend, offline dashboard, trained model weights, SQLite database schema, training/evaluation utilities, launchers, tests and Docker deployment files. The screens use real API data. No hardcoded detection results are substituted when a model is unavailable.

## Start in five minutes

Install **Python 3.12**. Python 3.11–3.13 are supported; validation was performed with Python 3.12 on Linux. Internet is needed once to install dependencies; the model is already included.

**Windows**

1. Extract this ZIP completely.
2. Double-click `start_windows.bat` (or run it from PowerShell).
3. Choose an administrator password of at least 12 characters when prompted.
4. Open **http://localhost:8000** and sign in as **admin** with your chosen password.

**Linux / macOS**

```bash
cd MathTech-Convoy-Vision-v1.0.0
bash start.sh
```

The launcher creates `.venv`, installs the pinned runtime and starts the server. On later launches it reuses the database and password. Stop it with Ctrl+C. No Node.js, npm build or external CDN is needed.

**First real run**

1. In Dashboard, click **Browse** and upload `samples/vehicle-validation.mp4` or your own road video.
2. Select **YOLOv8 Nano**, **Detection + Segmentation**, confidence **0.30**, and analysis FPS **5**.
3. Click **Run Analysis**. Input overlays, true instance masks, track IDs, mask area, image velocity and confidence charts update from the model.
4. Open **Analysis** to replay any persisted frame, inspect the summary or export CSV/JSON.
5. For live input, open **Live Feed → Enable camera → Analyze camera feed**, then click **Run Analysis** on Dashboard.

The sample clip is a short pan generated from Ultralytics' bus example image. It verifies codecs and inference wiring. Its motion is synthetic camera motion; it is not an aerial/convoy evaluation dataset.

## Working modules

| Module                   | Implemented behavior                                                                                                        |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| Dashboard                | Original/overlay/trail views, mask output, counts, selectable track rows, mask area and live confidence plot                |
| Video input              | Bounded upload, codec validation, CPU inference in background workers, sampling rate, pause/resume/stop                     |
| Live Feed                | Browser webcam/USB capture, binary JPEG WebSocket input, backpressure, session recording and disconnect recovery            |
| Detection + segmentation | Bundled YOLOv8n-seg ONNX; letterboxing, class-aware NMS, decoded instance masks and compressed contours                     |
| Tracking                 | Session IDs, center/IoU association, predicted-center matching, occlusion grace period, EMA image velocity and trajectories |
| Group status             | Explicit unverified proximity-and-image-motion candidate; no invented convoy confidence                                     |
| Analysis                 | SQLite session persistence, frame replay, per-run summary, charts, streaming CSV/JSON and JPEG snapshots                    |
| Dataset                  | Source-frame selection, polygon annotations, negative samples, persistence and YOLO segmentation ZIP export                 |
| Models                   | Checksum verification, warmup, offline custom ONNX registration, training and held-out evaluation scripts                   |
| Settings                 | Persisted defaults; current runs retain their saved configuration                                                           |
| Access                   | Hashed passwords, expiring HttpOnly cookie sessions, CSRF checks, admin/operator/viewer roles and user access revocation    |
| System health / logs     | Worker/storage status, audit events, error messages and filters                                                             |
| Deployment               | One-command local setup, non-root container, resource limits, healthcheck and HTTPS proxy example                           |

## What the model actually knows

The built-in COCO model is filtered to **car, bus, truck, motorcycle and bicycle**. It does **not** identify APCs, military affiliation, vehicle intent or geographic heading. The reference's APC/Jeep labels are not fabricated in the software. The masks segment **vehicle instances**, not road/background classes. This implementation uses the integrated YOLO segmentation head; it does not label that output as SAM.

All coordinates and motion are in the **analysis image**, resized with preserved aspect ratio to at most 1280 pixels on either side. Speeds are **pixels/second**. Downward is positive Y; image direction is clockwise from the rightward image axis. Without camera calibration and telemetry, the system does not report meters, altitude, compass directions or real-world speed.

Aerial viewpoint, distance, occlusion, lighting and unfamiliar vehicles can cause missed or incorrect detections. Thresholds tune output filtering; confidence is not measured accuracy. No aerial accuracy percentage, 30 FPS guarantee or production certification is claimed. Field validation on your own held-out footage is required. See `docs/VALIDATION.md` for the checks performed on this package.

## Docker

```bash
cp .env.example .env
# Edit .env and set ADMIN_PASSWORD to a unique password (12+ characters).
docker compose up --build -d
docker compose logs -f vision
```

Open **http://localhost:8000**. Data is retained in the `vision-data` named volume. Docker setup is supplied but was not executed in the validation environment. For remote deployment use HTTPS, set `PUBLIC_ORIGIN=https://your-hostname` and `COOKIE_SECURE=true`, and adapt `deployment/nginx.conf`. Do not set secure cookies for plain localhost HTTP.

**Run exactly one Uvicorn worker.** The in-process manager coordinates worker slots and live sessions. Multiple Uvicorn processes or replicas need an external job queue, shared object storage and a different database architecture; this package does not silently pretend to support that configuration.

## Manual startup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Bash: choose your own value. Do not reuse this literal text.
export ADMIN_PASSWORD='admin123'
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 4194304
```

In PowerShell use `.venv\Scripts\Activate.ps1` and `$env:ADMIN_PASSWORD = 'your-own-password'`. The direct Uvicorn command reads environment variables; the launchers and Docker Compose additionally load `.env`.

## Train on your own vehicle data

1. Upload multiple independent videos and annotate source frames in Dataset. Save each reviewed frame.
2. Export the dataset ZIP and extract it. Set `path` in `data.yaml` to that dataset's absolute directory. Add a real validation set if you only annotated one source.
3. Use a **separate training environment**, install matching PyTorch/torchvision, then `requirements-training.txt`.
4. Run `scripts/train.py`, evaluate the held-out split with `scripts/evaluate.py`, and register the exported ONNX file using `scripts/register_model.py`.

Complete commands, output requirements and dataset-split limitations are in `docs/MODELS.md`. Training, annotation and evaluation are real workflows, but this package has not trained a new aerial model or supplied invented experimental results.

## Test and maintain

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Stop the server before backup or password recovery:

```bash
python scripts/backup.py --output backups/vision-backup.zip
python scripts/reset_password.py --username admin
```

Restore by extracting the backup's `data/` folder into the stopped application's configured data location. Backup ZIPs contain uploaded images, media and authentication data; keep them private. `data/`, passwords and runtime logs are not part of the delivered source ZIP.

See `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DEPLOYMENT.md`, and `docs/TROUBLESHOOTING.md` for implementation and operations details.

## License and provenance

This distribution is **AGPL-3.0**; see `LICENSE`. Ultralytics model weights and training dependencies retain their licenses. Review `THIRD_PARTY_NOTICES.md` before commercial distribution or a closed-source deployment. Sources: [Ultralytics YOLOv8](https://docs.ultralytics.com/models/yolov8/), [segmentation](https://docs.ultralytics.com/tasks/segment/), [licensing](https://www.ultralytics.com/license).
