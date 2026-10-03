"""Short-term image-space tracking and an explicit, non-semantic grouping heuristic.

Greedy assignment combines predicted center distance and IoU; velocity is EMA
smoothed. IDs are session-local and are not reliable identities after long occlusion.
"""
from collections import deque
import math
import numpy as np

def overlap(a,b):
    left,top = max(a[0],b[0]),max(a[1],b[1])
    right,bottom = min(a[2],b[2]),min(a[3],b[3])
    intersection = max(0,right-left)*max(0,bottom-top)
    return intersection / max(1e-6,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)

class Tracker:
    def __init__(self, trail=40, max_age=2.0):
        self.trail, self.max_age = trail, max_age
        self.tracks, self.next_id = {},1

    def update(self, detections, timestamp, width, height):
        self.tracks = {k:v for k,v in self.tracks.items() if timestamp-v["time"] <= self.max_age}
        diagonal = math.hypot(width,height)
        candidates = []
        for i, detection in enumerate(detections):
            for tid,t in self.tracks.items():
                if t["class"] != detection["class_name"]:
                    continue
                dt = max(0,timestamp-t["time"])
                predicted = np.asarray(t["center"])+np.asarray(t["velocity"])*dt
                distance = float(np.linalg.norm(predicted-np.asarray(detection["center"]))) / diagonal
                iou = overlap(t["box"], detection["bbox"])
                # Avoid attaching arbitrarily distant objects even with a weak prediction.
                if iou >= .12 or distance < .055:
                    candidates.append((.65*iou+.35*(1-min(distance/.055,1)),i,tid))
        assignments, used_tracks = {},set()
        for _,i,tid in sorted(candidates,reverse=True):
            if i not in assignments and tid not in used_tracks:
                assignments[i] = tid
                used_tracks.add(tid)
        out = []
        for i,detection in enumerate(detections):
            tid = assignments.get(i)
            if tid is None:
                tid, self.next_id = self.next_id, self.next_id+1
                self.tracks[tid] = {"center": detection["center"],"box": detection["bbox"],
                  "velocity": [0.,0.],"time":timestamp,"first":timestamp,"class":detection["class_name"],
                  "hits":0,"history":deque(maxlen=max(1,self.trail))}
            track = self.tracks[tid]
            dt = timestamp-track["time"]
            if dt > 0:
                raw = (np.asarray(detection["center"])-np.asarray(track["center"]))/dt
                # Initialize on second hit; then smooth to reduce center jitter.
                track["velocity"] = raw if track["hits"] == 1 else .35*raw+.65*np.asarray(track["velocity"])
            track.update(center=detection["center"],box=detection["bbox"],time=timestamp,hits=track["hits"]+1)
            if self.trail:
                track["history"].append([*detection["center"],round(timestamp,3)])
            vx,vy = map(float,track["velocity"])
            speed = math.hypot(vx,vy)
            out.append({**detection,"id":tid,"age_seconds":round(timestamp-track["first"],3),
              "hits":track["hits"],"velocity":{"x":round(vx,2),"y":round(vy,2),"speed":round(speed,2)},
              "direction_image_deg":round(math.degrees(math.atan2(vy,vx))%360,1) if speed>=2 else None,
              "history":list(track["history"]) if self.trail else []})
        return out

def group_status(objects,width,height,min_group=3,radius=.35):
    """Proximity + coherent image motion. Camera movement can create false groups."""
    eligible = [o for o in objects if o["hits"] >= 3]
    adjacency = {o["id"]:set() for o in eligible}
    for i,a in enumerate(eligible):
        for b in eligible[i+1:]:
            distance = math.hypot((a["center"][0]-b["center"][0])/width,
                                  (a["center"][1]-b["center"][1])/height)
            av=np.array([a["velocity"]["x"],a["velocity"]["y"]]);bv=np.array([b["velocity"]["x"],b["velocity"]["y"]])
            norms=float(np.linalg.norm(av)*np.linalg.norm(bv))
            aligned = norms>25 and float(av@bv)/norms>.7
            if distance<radius and aligned:
                adjacency[a["id"]].add(b["id"]);adjacency[b["id"]].add(a["id"])
    best,visited=[],set()
    for tid in adjacency:
        if tid in visited:
            continue
        group,stack=[],[tid]
        while stack:
            v=stack.pop()
            if v not in visited:
                visited.add(v);group.append(v);stack.extend(adjacency[v]-visited)
        if len(group)>len(best):
            best=group
    found=len(best)>=min_group
    return {"candidate":found,"size":len(best) if found else 0,"track_ids":best if found else [],
            "method":"proximity_and_image_motion", "status":"Candidate moving group" if found else "No moving group candidate",
            "note":"Unverified image-space heuristic; camera motion is not compensated."}

