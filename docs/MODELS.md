# Models, training and measured evaluation

The package contains both the original `models/yolov8n-seg.pt` and its runtime `models/yolov8n-seg.onnx`. Inference requires only ONNX Runtime; PyTorch is not a runtime requirement. Model checksums and exact export settings are in `models/registry.json`.

## A separate training environment

From the project root, for Linux/macOS CPU training:

```bash
python3 -m venv .train-venv
source .train-venv/bin/activate
python -m pip install torch==2.7.0+cpu torchvision==0.22.0+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-training.txt
python scripts/train.py --data /absolute/path/dataset/data.yaml --weights models/yolov8n-seg.pt --epochs 100 --batch 8 --device cpu
```

For a GPU install matching CUDA wheels from the official PyTorch selector and use `--device 0`. Windows activation is `.train-venv\Scripts\Activate.ps1`. Training can consume substantial time and memory; lower the batch size if necessary. It is optional and does not block the included pretrained model.

The training script sets seed 42 and deterministic behavior, trains at 640, retains real run logs and exports the best checkpoint with `batch=1`, `dynamic=False`, `nms=False`, `simplify=False` and ONNX opset 17. It accepts only the generic vehicle labels `car`, `bus`, `truck`, `motorcycle`, `bicycle`. Run multiple seeds and independent datasets for research claims; deterministic settings alone do not establish reproducible accuracy across all hardware.

## Dataset preparation

In Dataset, choose a video and a source frame number, click around a vehicle, finish its polygon and save. Class IDs in exported datasets are `car=0, bus=1, truck=2, motorcycle=3, bicycle=4`. Saved empty frames are negative examples. Each saved frame is represented by an image and a YOLO polygon label text file; complex holes/multipart manual objects need dataset tooling beyond this single-polygon editor.

Export splits by source-video SHA-256 using seed 42, assigning approximately 20% of independent source videos to validation. A single source creates no independent validation split. Identical uploads remain in the same split, but transcoded copies and adjacent/overlapping scenes require manual group curation. The image-level frame editor does not magically make these samples statistically independent. Fix `path` in `data.yaml` after extracting the ZIP.

## Evaluate real held-out data

```bash
python scripts/evaluate.py --model training-runs/vehicles-seed42/weights/best.pt --data /absolute/path/dataset/data.yaml --split val --device cpu --output evaluation/heldout.json
```

The output records measured bounding-box and mask mAP50/mAP50–95, precision, recall and timing. `--split test` requires a configured test split. Keep all videos of the same scene in one split, never tune on test data, and report aerial-viewpoint, distance, occlusion, lighting and class-specific performance. Track quality additionally requires identity-labeled sequences and an external MOT evaluator (e.g. HOTA/IDF1); this package does not manufacture those metrics from confidence values.

## Register a trusted export

Activate the runtime environment and run:

```bash
python scripts/register_model.py /absolute/path/best.onnx --id aerial-vehicles-v1 --name "Aerial vehicles v1"
```

Restart the service, select the model in Models and click **Verify & warm up**. Registration checks static shapes, raw-output channels and generic vehicle names, computes its checksum and preserves the original bundled model. Only YOLOv8 raw ONNX exports in this layout are supported; a YOLO26/SAM/semantic/depth model cannot be silently dropped into this decoder. Model registration is a local administrator operation; executable Python/pickle checkpoint files are not uploaded through the dashboard.

