"""Reproducible vehicle segmentation training; no invented accuracy results."""
from pathlib import Path
import argparse
import json
import yaml
from ultralytics import YOLO

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data',type=Path,required=True)
parser.add_argument('--weights',default='yolov8n-seg.pt')
parser.add_argument('--epochs',type=int,default=100)
parser.add_argument('--batch',type=int,default=8)
parser.add_argument('--seed',type=int,default=42)
parser.add_argument('--device',default='cpu',help='cpu or a CUDA device index, e.g. 0')
parser.add_argument('--output',type=Path,default=Path('training-runs'))
args=parser.parse_args()
data=yaml.safe_load(args.data.read_text())
names=data.get('names',{})
names=list(names.values()) if isinstance(names,dict) else names
if not names or not set(names).issubset({'car','bus','truck','motorcycle','bicycle'}):
    raise SystemExit('Use only generic vehicle classes in data.yaml')
if args.epochs<1 or args.batch<1:
    raise SystemExit('Epochs and batch size must be positive')
model=YOLO(args.weights,task='segment')
results=model.train(data=str(args.data.resolve()),epochs=args.epochs,batch=args.batch,seed=args.seed,
                   deterministic=True,imgsz=640,device=args.device,project=str(args.output),name=f'vehicles-seed{args.seed}',exist_ok=False)
best=Path(results.save_dir)/'weights/best.pt'
trained=YOLO(str(best))
onnx=trained.export(format='onnx',imgsz=640,opset=17,batch=1,dynamic=False,simplify=False,nms=False,device='cpu')
print('Best weights:',best)
print('Register this ONNX file:',onnx)

