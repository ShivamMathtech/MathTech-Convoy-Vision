# Validation record

Validation performed on **3 October 2026** using Python **3.12.14**, Linux x86-64 and the pinned runtime in `requirements.txt` / `constraints.txt`. A clean virtual environment containing only runtime/test dependencies was used for final integration and browser checks. `pip check` reported no dependency conflicts. The actual dashboard was rendered and inspected at desktop and mobile widths.

## Automated integration suite

**12 tests passed.** These use real OpenCV codecs, the bundled ONNX model, FastAPI requests, WebSockets and SQLite persistence.

- Unauthenticated access, credentials, login Origin, CSRF enforcement and viewer role permissions.
- Actual video upload, sampled analysis, completion, four replay image views, summary, CSV/JSON exports and reference-aware deletion.
- Invalid codecs/extensions, upload limits, missing media and settings validation.
- Polygon save/read, coordinate bounds, negative frames and YOLO dataset ZIP contents.
- Neural bus detection and a nonrectangular instance mask with nonzero area; detection-only mode omits masks.
- Model checksum rejection.
- Tracker association, timestamps, occlusion, velocity and ID expiry.
- Explicit proximity-and-motion grouping behavior.
- Live JPEG WebSocket ingestion, pause/resume/stop and recorded-frame replay.
- JPEG dimensions/header validation.
- Restart recovery marks unfinished runs interrupted.
- Update WebSocket returns the final persisted file state.

The test runner emits one upstream Starlette deprecation warning about the httpx TestClient adapter; the tests pass. This concerns test tooling and is not a runtime inference error.

## Actual browser workflow

An actual Chromium headless browser ran the application against a spawned Uvicorn server and completed:

1. Sign-in, video upload, real ONNX segmentation and object-table updates.
2. Overlay/mask/trail image loading and saved-frame seeking.
3. Analysis summary and downloading/parsing a JSON export with **15** sampled frames, including real bus masks.
4. Polygon drawing/saving and a dataset ZIP download.
5. Model checksum verification/warmup, settings save, system health and audit-log reads.
6. Browser camera capture using Chromium's synthetic camera, real binary WebSockets, JPEG decode, actual ONNX inference, pause/resume/stop.
7. Responsive layout at **1600 px** and **390 px** width with no page-level horizontal overflow and no unexpected JavaScript errors.

The synthetic camera check validates transport and workflow. It is not a claim that a physical camera or drone adapter was tested. `tests/e2e.cjs` contains the optional browser test; install Playwright and a compatible Chromium browser separately to rerun it. Set `PYTHON_EXECUTABLE` for the runtime interpreter if it is outside the project's `.venv`.

```bash
# Optional developer browser test, after local runtime setup:
npm install --no-save playwright
npx playwright install chromium
node tests/e2e.cjs
```

## Model decoder parity

On the original Ultralytics bus example image, the custom ONNX decoder was compared with the original `.pt` model using Ultralytics, square 640 input, `rect=False`, `retina_masks=True`, confidence 0.30 and NMS IoU 0.50.

| Check | Measured value |
|---|---:|
| Bus confidence | 0.86125 |
| Maximum bounding-box coordinate difference | approximately 0.0044 px |
| Confidence difference | approximately 0.0000032 |
| Reconstructed mask IoU with original model output | approximately 0.99904 |

This is a **one-image decoder consistency check**, not an accuracy result or a test-set mAP. It verifies that the runtime interprets the actual learned mask outputs correctly. No target-domain vehicle ground truth or new training experiment was available.

## Checks still required on your deployment

Docker/Compose, HTTPS proxy integration, Windows/macOS launchers, physical cameras, actual drone imagery, long-duration streaming, multi-user load and trained custom models have not been field-validated here. Their implementations and setup instructions are included. Validate these on your intended host and collect independent labeled footage before making operational performance or accuracy claims.

