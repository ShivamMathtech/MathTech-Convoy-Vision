# Third-party notices

The application source is released under GNU AGPL version 3.0. The full text is in `LICENSE`.

| Component | Source | License / use |
|---|---|---|
| YOLOv8n-seg pretrained checkpoint | `https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-seg.pt` | Ultralytics AGPL-3.0; original `.pt` included for reproducibility |
| YOLOv8n-seg ONNX | Locally exported from the above checkpoint with Ultralytics 8.3.128, PyTorch 2.7.0+cpu, ONNX opset 17 | Same model provenance/license; checksum recorded in `models/registry.json` |
| Validation bus image | `https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg` | Ultralytics example asset; included only for wiring/inference tests |
| Validation video | A 45-frame translated pan of the validation bus image, generated locally | Derived example; artificial camera motion, not a field dataset |
| FastAPI | `https://github.com/fastapi/fastapi` | MIT |
| Starlette | `https://github.com/encode/starlette` | BSD-3-Clause |
| Uvicorn | `https://github.com/encode/uvicorn` | BSD-3-Clause |
| ONNX Runtime | `https://github.com/microsoft/onnxruntime` | MIT |
| OpenCV | `https://github.com/opencv/opencv` | Apache-2.0; wheels have their own bundled codec notices |
| NumPy | `https://github.com/numpy/numpy` | BSD-3-Clause |
| Pydantic | `https://github.com/pydantic/pydantic` | MIT |
| python-multipart | `https://github.com/Kludex/python-multipart` | Apache-2.0 |
| websockets | `https://github.com/python-websockets/websockets` | BSD-3-Clause |

Runtime dependencies are installed from their upstream packages rather than vendored in this ZIP. Retain their notices when redistributing installed binaries. Optional training additionally uses Ultralytics, PyTorch, torchvision and ONNX under their upstream licenses. Ultralytics offers an enterprise licensing route for deployments that do not use its AGPL terms; see `https://www.ultralytics.com/license` for current information.

UI icons are original simple SVG path drawings in `frontend/app.js`. The MathTech shield in `frontend/logo.svg` is an original code-drawn asset for this package. No third-party CDN, tracking script or external font is loaded by the dashboard.

