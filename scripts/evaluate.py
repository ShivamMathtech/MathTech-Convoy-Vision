"""Evaluate box and mask metrics on a real held-out split using Ultralytics."""
from pathlib import Path
import argparse
import json
import platform
from ultralytics import YOLO

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model',type=Path,required=True)
parser.add_argument('--data',type=Path,required=True)
parser.add_argument('--split',choices=['val','test'],default='val')
parser.add_argument('--device',default='cpu')
parser.add_argument('--output',type=Path,default=Path('evaluation.json'))
args=parser.parse_args()
model=YOLO(str(args.model))
metrics=model.val(data=str(args.data.resolve()),split=args.split,imgsz=640,device=args.device,plots=True)
def collect(m):
    return {'mAP50_95':float(m.map),'mAP50':float(m.map50),'precision':m.p.tolist(),'recall':m.r.tolist()}
report={'model':str(args.model),'dataset':str(args.data),'split':args.split,'box':collect(metrics.box),
        'speed_ms':metrics.speed,'platform':platform.platform(),'names':metrics.names}
if hasattr(metrics,'seg'):
    report['mask']=collect(metrics.seg)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
print('Saved measured metrics to',args.output)

