"""Bounded background video workers with persisted frame metadata and replay."""
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import math
import shutil
import threading
import time
import uuid
import cv2
from .tracking import Tracker, group_status
from .vision import paint, jpeg

def storage_bytes(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())

def analysis_image(image):
    h,w=image.shape[:2]
    scale=min(1.,1280/w,1280/h)
    return cv2.resize(image,(round(w*scale),round(h*scale))) if scale<1 else image

@dataclass
class Runtime:
    id: str
    config: dict
    tracker: Tracker
    model: object
    gate: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest: dict | None = None
    image: object = None
    sequence: int = 0
    started: float = field(default_factory=time.monotonic)
    last_live_time: float = 0
    last_activity: float = field(default_factory=time.monotonic)
    status: str = "running"
    def __post_init__(self):
        self.gate.set()

class JobManager:
    def __init__(self,db,registry,config):
        self.db,self.registry,self.config=db,registry,config
        self.runtimes={}
        self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=config.max_jobs,thread_name_prefix="video")
        self.closed=threading.Event()
        self.reaper=threading.Thread(target=self._reap,daemon=True,name="live-idle")
        self.reaper.start()

    def _reap(self):
        while not self.closed.wait(5):
            with self.lock:
                idle=[r for r in self.runtimes.values() if r.config["source"]=="camera" and
                      r.status in ("running","paused") and time.monotonic()-r.last_activity>60]
            for runtime in idle:
                with runtime.lock:
                    if time.monotonic()-runtime.last_activity>60:
                        self.finish(runtime,"interrupted","Camera disconnected for more than 60 seconds")

    def close(self):
        self.closed.set()
        with self.lock:
            runtimes=list(self.runtimes.values())
        for runtime in runtimes:
            runtime.stop.set();runtime.gate.set()
            if runtime.config["source"]=="camera":
                with runtime.lock:
                    self.finish(runtime,"interrupted","Service shutting down")
        self.pool.shutdown(wait=True,cancel_futures=True)

    def create(self,body,user):
        config=body.model_dump()
        if config["source"]=="file":
            media=self.db.one("SELECT * FROM media WHERE id=?",(config["media_id"],))
            if not media:
                raise ValueError("Choose an uploaded video")
            expected=math.ceil(media["duration"]*min(config["analysis_fps"],media["fps"]))
            if expected>self.config.max_frames:
                raise ValueError(f"Run would exceed {self.config.max_frames} analyzed frames. Lower Analysis FPS or use a shorter video.")
        elif config["media_id"]:
            raise ValueError("Camera sessions do not take a media_id")
        model=self.registry.get(config["model_id"])
        if config["mode"]=="segment" and model.item["task"]!="segment":
            raise ValueError("Choose a segmentation model for mask analysis")
        with self.lock:
            active=sum(r.status in ("running","paused") for r in self.runtimes.values())
            if active>=self.config.max_jobs:
                raise ValueError(f"All {self.config.max_jobs} worker slots are in use. Stop a run first.")
            if storage_bytes(self.config.data_dir)>=self.config.max_storage_mb*1024*1024:
                raise ValueError("Storage quota reached; delete old sessions or media")
            jid=str(uuid.uuid4());now=time.time()
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",(jid,config["name"],config["media_id"],
                            config["source"],"running",json.dumps(config),now,now,None,user["id"]))
            runtime=Runtime(jid,config,Tracker(config["trail_length"]),model)
            self.runtimes[jid]=runtime
            self.db.event("Analysis started",job_id=jid,actor=user["username"])
            if config["source"]=="file":
                self.pool.submit(self.run_video,runtime,media)
            else:
                (self.config.data_dir / "captures" / jid).mkdir(parents=True)
            return self.job(jid)

    def job(self,jid):
        row=self.db.one("SELECT j.*,m.duration,m.fps AS source_fps,m.frame_count AS total_source_frames FROM jobs j LEFT JOIN media m ON m.id=j.media_id WHERE j.id=?",(jid,))
        if not row:
            return None
        row["config"]=json.loads(row["config"])
        info=self.db.one("SELECT COUNT(*) AS analyzed_frames,MAX(timestamp) AS analyzed_seconds FROM frames WHERE job_id=?",(jid,))
        row.update(info)
        if row["source"]=="file":
            row["progress"]=1 if row["status"]=="completed" else min(1,(row["analyzed_seconds"] or 0)/max(.001,row["duration"] or .001))
        else:
            row["progress"]=None
        return row

    def finish(self,runtime,status,error=None):
        with self.lock:
            runtime.status=status
            runtime.stop.set();runtime.gate.set()
            self.db.execute("UPDATE jobs SET status=?,updated=?,error=? WHERE id=?",(status,time.time(),error,runtime.id))
            self.db.event(error or f"Analysis {status}","ERROR" if status=="failed" else "INFO",runtime.id)
            # Completed runs are replayed from SQLite. Drop heavy images/track state immediately.
            self.runtimes.pop(runtime.id,None)

    def control(self,jid,action):
        with self.lock:
            runtime=self.runtimes.get(jid)
            if not runtime or runtime.status not in ("running","paused"):
                raise ValueError("Run has finished; use replay or start a new analysis")
            if action=="pause":
                runtime.gate.clear();runtime.status="paused"
            elif action=="resume":
                runtime.gate.set();runtime.status="running";runtime.last_activity=time.monotonic()
            else:
                runtime.stop.set();runtime.gate.set();runtime.status="stopped"
                if runtime.config["source"]=="camera":
                    self.finish(runtime,"stopped")
                    return self.job(jid)
            self.db.execute("UPDATE jobs SET status=?,updated=? WHERE id=?",(runtime.status,time.time(),jid))
            self.db.event(f"Analysis {action}",job_id=jid)
            return self.job(jid)

    def run_video(self,runtime,media):
        cap=cv2.VideoCapture(str(self.config.data_dir/"uploads"/media["filename"]))
        try:
            if not cap.isOpened():
                raise ValueError("Video decoder could not open the uploaded video")
            stride=max(1,round(media["fps"]/runtime.config["analysis_fps"]))
            source_frame=0
            while not runtime.stop.is_set():
                if not runtime.gate.wait(.25):
                    continue
                ok,image=cap.read()
                if not ok:
                    if source_frame<media["frame_count"]-stride-2:
                        raise ValueError("Video decoder stopped before the expected end")
                    break
                if runtime.sequence>=self.config.max_frames:
                    raise ValueError("Analyzed frame limit reached")
                with runtime.lock:
                    if runtime.stop.is_set():
                        break
                    self.process(runtime,image,source_frame/media["fps"],source_frame)
                for _ in range(stride-1):
                    if not cap.grab():
                        break
                source_frame+=stride
            self.finish(runtime,"stopped" if runtime.stop.is_set() else "completed")
        except Exception as exc:
            self.finish(runtime,"failed",str(exc)[:300])
        finally:
            cap.release()

    def process(self,runtime,image,timestamp,source_frame):
        image=analysis_image(image)
        h,w=image.shape[:2]
        started=time.perf_counter()
        c=runtime.config
        detections=runtime.model.predict(image,c["confidence"],c["iou"],c["mode"]=="segment")
        inference_ms=(time.perf_counter()-started)*1000
        objects=runtime.tracker.update(detections,timestamp,w,h)
        seq=runtime.sequence
        result={"seq":seq,"source_frame":source_frame,"timestamp":round(timestamp,4),"width":w,"height":h,
          "objects":objects,"group":group_status(objects,w,h,c["min_group"],c["group_radius"]),
          "inference_ms":round(inference_ms,2),"processing_fps":round((seq+1)/max(.001,time.monotonic()-runtime.started),2),
          "model_id":c["model_id"],"mode":c["mode"],"coordinate_space":"analysis_image_pixels"}
        if seq%50==0 and storage_bytes(self.config.data_dir)>=self.config.max_storage_mb*1024*1024:
            raise ValueError("Storage quota reached; delete old sessions")
        if c["source"]=="camera":
            path=self.config.data_dir/"captures"/runtime.id/f"{seq:08d}.jpg"
            path.write_bytes(jpeg(image))
        self.db.execute("INSERT INTO frames VALUES(?,?,?,?,?)",(runtime.id,seq,source_frame,timestamp,json.dumps(result,separators=(",",":"))))
        runtime.sequence+=1
        runtime.latest=result
        runtime.image=image
        runtime.last_activity=time.monotonic()
        if seq%10==0:
            self.db.execute("UPDATE jobs SET updated=? WHERE id=?",(time.time(),runtime.id))
        return result

    def process_live(self,jid,image):
        runtime=self.runtimes.get(jid)
        if not runtime:
            raise ValueError("Camera session ended")
        runtime.last_activity=time.monotonic()
        with runtime.lock:
            if runtime.stop.is_set():
                raise ValueError("Camera session ended")
            if not runtime.gate.is_set():
                return None
            elapsed=time.monotonic()-runtime.started
            if elapsed>self.config.max_live_seconds or runtime.sequence>=self.config.max_frames:
                self.finish(runtime,"completed","Live capture limit reached")
                return None
            if elapsed-runtime.last_live_time < 1/runtime.config["analysis_fps"]:
                return None
            runtime.last_live_time=elapsed
            return self.process(runtime,image,elapsed,runtime.sequence)

    def result(self,jid,seq=None):
        runtime=self.runtimes.get(jid)
        if runtime and runtime.latest and (seq is None or seq==runtime.latest["seq"]):
            return runtime.latest
        if seq is None:
            row=self.db.one("SELECT result FROM frames WHERE job_id=? ORDER BY seq DESC LIMIT 1",(jid,))
        else:
            row=self.db.one("SELECT result FROM frames WHERE job_id=? AND seq=?",(jid,seq))
        return json.loads(row["result"]) if row else None

    def frame(self,jid,seq,view):
        result=self.result(jid,seq)
        job=self.job(jid)
        if not result or not job:
            return None
        runtime=self.runtimes.get(jid)
        if runtime and runtime.latest and runtime.latest["seq"]==seq:
            with runtime.lock:
                # The worker may advance while this request waits for its frame lock.
                image=runtime.image if runtime.latest and runtime.latest["seq"]==seq else None
            if image is None:
                return self.frame(jid,seq,view)
        elif job["source"]=="camera":
            image=cv2.imread(str(self.config.data_dir/"captures"/jid/f"{seq:08d}.jpg"))
        else:
            media=self.db.one("SELECT filename FROM media WHERE id=?",(job["media_id"],))
            cap=cv2.VideoCapture(str(self.config.data_dir/"uploads"/media["filename"]))
            try:
                cap.set(cv2.CAP_PROP_POS_FRAMES,result["source_frame"])
                ok,image=cap.read()
                if not ok:
                    return None
            finally:
                cap.release()
        if image is None:
            return None
        if image.shape[:2] != (result["height"], result["width"]):
            image=cv2.resize(image,(result["width"],result["height"]))
        if view!="original":
            image=paint(image,result,view,job["config"]["mask_opacity"],job["config"]["show_labels"])
        return jpeg(image)

    def delete(self,jid):
        with self.lock:
            if jid in self.runtimes:
                raise ValueError("Stop the run and wait for it to finish before deleting")
            self.db.execute("DELETE FROM jobs WHERE id=?",(jid,))
            shutil.rmtree(self.config.data_dir/"captures"/jid,ignore_errors=True)

    def summary(self,jid):
        rows=self.db.all("SELECT result FROM frames WHERE job_id=? ORDER BY seq",(jid,))
        tracks,classes={},{}
        confidence_sum=latency_sum=observations=groups=0
        series=[]
        for row in rows:
            r=json.loads(row["result"])
            latency_sum+=r["inference_ms"];groups+=int(r["group"]["candidate"])
            for obj in r["objects"]:
                observations+=1;confidence_sum+=obj["confidence"]
                classes[obj["class_name"]]=classes.get(obj["class_name"],0)+1
                tracks[obj["id"]]={"id":obj["id"],"class_name":obj["class_name"],"age_seconds":obj["age_seconds"]}
            series.append({"time":r["timestamp"],"count":len(r["objects"]),"confidence":sum(o["confidence"] for o in r["objects"])/max(1,len(r["objects"])),"latency":r["inference_ms"]})
        # Keep full persisted frames for export; downsample only the overview chart.
        chart_stride=max(1,math.ceil(len(series)/300))
        return {"analyzed_frames":len(rows),"object_observations":observations,"unique_track_ids":len(tracks),
          "mean_confidence":round(confidence_sum/max(1,observations),4),
          "mean_inference_ms":round(latency_sum/max(1,len(rows)),2),"group_candidate_frames":groups,
          "class_observations":classes,"tracks":list(tracks.values()),"series":series[::chart_stride]}
