"""CPU ONNX YOLOv8 raw-output inference: letterbox, class-aware NMS, real masks.

Only generic vehicle categories are returned. Other COCO classes are filtered.
Weights are allowlisted by SHA-256; no HTTP model execution or pickle uploads.
"""
import ast
import hashlib
import json
import threading
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort

VEHICLES = {"car", "bus", "truck", "motorcycle", "bicycle"}
COLORS = {"truck": (244, 75, 91), "car": (66, 145, 255), "bus": (36, 211, 162),
          "motorcycle": (246, 177, 60), "bicycle": (173, 117, 255)}  # RGB

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def letterbox(image, size):
    h, w = image.shape[:2]
    ratio = min(size / h, size / w)
    nw, nh = round(w * ratio), round(h * ratio)
    left, top = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top:top+nh, left:left+nw] = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.
    return tensor, (ratio, left, top, nw, nh)

def contours(mask):
    rings, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    out = []
    for ring, info in zip(rings, hierarchy[0]):
        if cv2.contourArea(ring) < 4:
            continue
        # Tight compression for persisted replay; area remains the true raster mask pixel count.
        poly = cv2.approxPolyDP(ring, .5, True).reshape(-1, 2)
        if len(poly) >= 3:
            out.append({"points": poly.tolist(), "hole": bool(info[3] >= 0)})
    return out

class ModelRegistry:
    def __init__(self, directory, threads=2):
        self.directory, self.threads = directory, threads
        self._models, self._lock = {}, threading.Lock()

    def entries(self):
        path = self.directory / "registry.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        return data["models"]

    def list(self):
        return [{**entry, "available": (self.directory / entry["file"]).is_file(),
                 "loaded": entry["id"] in self._models} for entry in self.entries()]

    def get(self, model_id):
        with self._lock:
            item = next((x for x in self.entries() if x["id"] == model_id), None)
            if not item:
                raise ValueError("Model is not registered")
            path = (self.directory / item["file"]).resolve()
            if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
                raise ValueError("Model file is missing or outside the configured model directory")
            if item.get("format") != "yolov8_raw":
                raise ValueError("Only static YOLOv8 raw ONNX exports are supported")
            if sha256(path) != item["sha256"]:
                raise ValueError("Model checksum mismatch. Restore weights or register a reviewed model.")
            if model_id in self._models:
                return self._models[model_id]
            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, self.threads)
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
            model = OnnxModel(session, item)
            self._models[model_id] = model
            return model

class OnnxModel:
    def __init__(self, session, item):
        self.session, self.item = session, item
        self.lock = threading.Lock()
        inputs = session.get_inputs()
        shape = inputs[0].shape
        size = item["input_size"]
        if len(inputs) != 1 or shape != [1, 3, size, size]:
            raise ValueError("Export must use batch=1, static square input and dynamic=False")
        self.input_name, self.size = inputs[0].name, size
        metadata = session.get_modelmeta().custom_metadata_map
        names = item.get("names") or ast.literal_eval(metadata.get("names", "{}"))
        self.names = {int(k): v for k, v in names.items()}
        self.num_classes = len(self.names)
        if sorted(self.names) != list(range(self.num_classes)):
            raise ValueError("Model class IDs must be consecutive from zero")
        self.vehicle_ids = [i for i, name in self.names.items() if name in VEHICLES]
        if not self.vehicle_ids:
            raise ValueError("Model must include at least one supported generic vehicle class")

    def predict(self, image, confidence=.3, iou=.5, segment=True):
        tensor, (ratio, left, top, nw, nh) = letterbox(image, self.size)
        with self.lock:
            outputs = self.session.run(None, {self.input_name: tensor})
        predictions = outputs[0]
        if predictions.ndim != 3 or predictions.shape[0] != 1:
            raise ValueError("Unexpected raw YOLOv8 output shape")
        rows = predictions[0].T
        prototypes = outputs[1][0] if len(outputs) > 1 else None
        mask_dim = prototypes.shape[0] if prototypes is not None else 0
        if rows.shape[1] != 4 + self.num_classes + mask_dim:
            raise ValueError("Unsupported output layout: use YOLOv8, nms=False, opset=17")
        if segment and prototypes is None:
            raise ValueError("This model has no instance segmentation head")
        # Best class is selected across ALL classes, then non-vehicle detections are discarded.
        classes = rows[:, 4:4+self.num_classes].argmax(axis=1)
        scores = rows[np.arange(len(rows)), classes + 4]
        keep = (scores >= confidence) & np.isin(classes, self.vehicle_ids)
        rows, classes, scores = rows[keep], classes[keep], scores[keep]
        if not len(rows):
            return []
        boxes = rows[:, :4].copy()
        boxes[:, :2] -= boxes[:, 2:] / 2  # xywh -> top-left xywh in letterboxed coordinates
        selected = []
        for class_id in np.unique(classes):
            members = np.flatnonzero(classes == class_id)
            nms = cv2.dnn.NMSBoxes(boxes[members].tolist(), scores[members].tolist(), confidence, iou)
            selected.extend(members[np.asarray(nms, dtype=int).reshape(-1)].tolist())
        selected = sorted(selected, key=lambda k: -float(scores[k]))[:100]
        h, w = image.shape[:2]
        detections = []
        for k in selected:
            x, y, bw, bh = boxes[k]
            x1, y1 = np.clip((x-left)/ratio, 0, w), np.clip((y-top)/ratio, 0, h)
            x2, y2 = np.clip((x+bw-left)/ratio, 0, w), np.clip((y+bh-top)/ratio, 0, h)
            if x2-x1 < 1 or y2-y1 < 1:
                continue
            item = {"class_id": int(classes[k]), "class_name": self.names[int(classes[k])],
                    "confidence": round(float(scores[k]), 5), "bbox": [round(float(v), 2) for v in (x1,y1,x2,y2)],
                    "center": [round(float((x1+x2)/2), 2), round(float((y1+y2)/2), 2)],
                    "bbox_area_px": int((x2-x1)*(y2-y1)), "mask_area_px": None, "contours": []}
            if segment:
                coefficients = rows[k, 4+self.num_classes:]
                logits = (coefficients @ prototypes.reshape(mask_dim, -1)).reshape(prototypes.shape[1:])
                logits = cv2.resize(logits, (self.size, self.size), interpolation=cv2.INTER_LINEAR)
                logits = cv2.resize(logits[top:top+nh, left:left+nw], (w,h), interpolation=cv2.INTER_LINEAR)
                mask = (logits > 0).astype(np.uint8)
                crop = np.zeros((h, w), np.uint8)
                crop[int(np.ceil(y1)):int(np.ceil(y2)), int(np.ceil(x1)):int(np.ceil(x2))] = 1
                mask &= crop
                item["mask_area_px"] = int(mask.sum())
                item["contours"] = contours(mask)
            detections.append(item)
        return detections

def paint(image, result, view="overlay", opacity=.48, labels=True, selected=None):
    canvas = image.copy() if view != "mask" else (image.astype(np.float32)*.12).astype(np.uint8)
    h,w = image.shape[:2]
    for obj in result.get("objects", []):
        rgb = COLORS.get(obj["class_name"], (150,150,150))
        bgr = tuple(reversed(rgb))
        if view in ("overlay", "mask") and obj.get("contours"):
            raster = np.zeros((h,w), np.uint8)
            for ring in obj["contours"]:
                if not ring["hole"]:
                    cv2.fillPoly(raster, [np.asarray(ring["points"], np.int32)], 1)
            for ring in obj["contours"]:
                if ring["hole"]:
                    cv2.fillPoly(raster, [np.asarray(ring["points"], np.int32)], 0)
            pixels = raster.astype(bool)
            alpha = .85 if view == "mask" else opacity
            canvas[pixels] = (canvas[pixels]*(1-alpha)+np.asarray(bgr)*alpha).astype(np.uint8)
        if view in ("overlay", "trail"):
            x1,y1,x2,y2 = map(int,obj["bbox"])
            thickness = 4 if selected == obj.get("id") else 2
            cv2.rectangle(canvas,(x1,y1),(x2,y2),bgr,thickness)
            trail = np.asarray([p[:2] for p in obj.get("history", [])], np.int32)
            if len(trail) > 1:
                cv2.polylines(canvas,[trail],False,bgr,2,cv2.LINE_AA)
            center = tuple(map(int,obj["center"]))
            cv2.circle(canvas,center,3,bgr,-1)
            if labels:
                text = f'{obj["class_name"]} #{obj.get("id",0)} {obj["confidence"]:.2f}'
                cv2.rectangle(canvas,(x1,max(0,y1-22)),(min(w,x1+len(text)*8),y1),bgr,-1)
                cv2.putText(canvas,text,(x1+3,max(13,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1,cv2.LINE_AA)
    return canvas

def jpeg(image, max_width=1440):
    if image.shape[1] > max_width:
        image = cv2.resize(image,(max_width,round(image.shape[0]*max_width/image.shape[1])))
    ok, encoded = cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,85])
    if not ok:
        raise ValueError("Frame encoding failed")
    return encoded.tobytes()
