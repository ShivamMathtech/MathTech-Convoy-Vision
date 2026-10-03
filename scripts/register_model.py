"""Offline admin operation: register a reviewed static YOLOv8 ONNX model."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
import onnxruntime as ort

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('model',type=Path,help='Trusted local .onnx export; batch=1, nms=False, dynamic=False, opset=17')
parser.add_argument('--id',required=True)
parser.add_argument('--name',required=True)
parser.add_argument('--models-dir',type=Path,default=ROOT/'models')
args=parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',args.id) or len(args.name)>100:
    sys.exit('Invalid model identifier/name')
if args.id=='yolov8n-seg':
    sys.exit('Choose a new ID; preserve the bundled model')
if args.model.suffix.lower()!='.onnx':
    sys.exit('Register ONNX only. Export trusted training weights using scripts/train.py first.')
session=ort.InferenceSession(str(args.model),providers=['CPUExecutionProvider'])
shape=session.get_inputs()[0].shape
if len(shape)!=4 or shape[:2]!=[1,3] or not isinstance(shape[2],int) or shape[2]!=shape[3]:
    sys.exit('Use a static square input with batch=1')
names=ast.literal_eval(session.get_modelmeta().custom_metadata_map.get('names','{}'))
allowed={'car','bus','truck','motorcycle','bicycle'}
if not names or not set(names.values()).issubset(allowed):
    sys.exit('Custom models must use the generic vehicle labels: car, bus, truck, motorcycle, bicycle')
task='segment' if len(session.get_outputs())==2 else 'detect'
if task=='segment' and len(session.get_outputs()[1].shape)!=4:
    sys.exit('Unsupported segmentation output')
channels=session.get_outputs()[0].shape[1]
mask_dim=session.get_outputs()[1].shape[1] if task=='segment' else 0
if channels!=4+len(names)+mask_dim:
    sys.exit('Output is not raw YOLOv8. Export with nms=False.')
args.models_dir.mkdir(parents=True,exist_ok=True)
registry_path=args.models_dir/'registry.json'
registry=json.loads(registry_path.read_text()) if registry_path.exists() else {'models':[]}
if any(m['id']==args.id for m in registry['models']):
    sys.exit('Model ID already exists. Use a versioned new ID.')
target=args.models_dir/(args.id+'.onnx')
if target.exists():
    sys.exit('Destination file already exists')
shutil.copyfile(args.model,target)
entry={'id':args.id,'name':args.name,'file':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
       'input_size':shape[2],'format':'yolov8_raw','task':task,'names':names,
       'license':'AGPL-3.0','source':'Local operator-reviewed training export'}
registry['models'].append(entry)
temporary=registry_path.with_suffix('.json.tmp')
temporary.write_text(json.dumps(registry,indent=2)+'\n');temporary.replace(registry_path)
print('Registered',args.id,'— restart the service to load the updated registry.')

