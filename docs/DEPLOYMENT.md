# Deployment and operations

This package is a tested single-node baseline with deployment hardening. It is not a certification that all hardware, codecs, camera devices and target environments have been field-tested.

## Capacity

Defaults: two concurrent file/camera jobs, two ONNX CPU threads per model, 512 MiB per upload, 10 GiB total data quota, 30,000 analyzed frames per run and one hour per live session. Settings are environment driven in `.env.example`. Local files are analyzed as quickly as hardware permits; analysis FPS means source-video sampling, not realtime playback speed. Frame masks are computed in the resized analysis image. CPU performance depends on scene density and disk decoding.

SQLite WAL and short-lived connections allow HTTP queries alongside inference. Long JSON exports hold a read snapshot while streaming, so very long downloads can grow the WAL until they finish. Quotas are enforced before uploads/runs and periodically during processing. Leave disk headroom: quotas are not an exact filesystem reservation across every byte written. Stop/delete completed sessions before removing referenced media.

Use local persistent SSD storage with private filesystem permissions. Networked SQLite volumes are not supported. Runtime, video decoding and model execution require enough RAM; the supplied container limit is 3 GiB, which must be tuned and measured for your workload.

## HTTPS and browser camera

Bind the application to loopback, terminate HTTPS in a reverse proxy and configure `PUBLIC_ORIGIN` and `COOKIE_SECURE`. The Nginx location example is supplied; you must supply your own server block, DNS and TLS certificate. Only trusted proxy addresses should set forwarded headers. The dashboard uses one origin and needs no permissive CORS configuration. For browser cameras, localhost is a secure-context exception; a plain HTTP LAN address generally cannot access a webcam.

Keep the server timezone and host clock accurate, restrict host/network access as appropriate and install dependency/security updates through a tested release process. Package pins record the tested environment; they are not a permanent guarantee against future vulnerabilities.

## Service restarts

Completed sessions survive restarts. Active jobs become `interrupted` and can be replayed up to their last saved frame. Rerun the selected file to restart analysis with a fresh tracker. A lost browser camera connection pauses the capture and is ended after 60 seconds without activity; start a new session to reconnect.

## Backups

Stop active runs and the server, then use `scripts/backup.py`. It creates a SQLite backup snapshot and copies uploaded/captured media. Keep backups outside `DATA_DIR`. Restore only with the service stopped. For Docker, use a maintenance container that mounts the named volume and copies the backup helper, or make a host backup of the stopped named volume. No automated off-host backup destination is configured.

## Logs and access

Errors visible in the job/status panel also appear in System Logs. Unexpected API exceptions are logged by Uvicorn to stderr with detailed diagnostics; client errors avoid exposing server paths. Administrators create operator and viewer accounts. Access revocation invalidates stored sessions and the account password; keep historical rows for audit integrity. Password recovery is a local admin operation with `scripts/reset_password.py`.

## Release checks

Run the automated suite, verify the model checksum/warmup, process a short representative private video, inspect masks manually, test the intended camera and run a soak/load test at target concurrency. Measure precision/recall and mask mAP on independently labeled target-domain footage before claiming detection quality. Deployment files need validation on the actual Docker/reverse-proxy host.

