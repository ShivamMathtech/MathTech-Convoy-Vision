"""Authenticated API and same-origin dashboard. Run exactly one Uvicorn process."""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .auth import Auth, current_user, password_hash, require_role, token_hash
from .config import Config, ROOT
from .db import Database
from .jobs import JobManager, analysis_image, storage_bytes
from .schemas import Annotation, Control, JobCreate, Login, Settings, UserCreate
from .vision import ModelRegistry, VEHICLES, jpeg

class Limiter:
    def __init__(self):
        self.items=defaultdict(deque);self.lock=threading.Lock()
    def allow(self,key,limit,seconds=60):
        now=time.monotonic()
        with self.lock:
            queue=self.items[key]
            while queue and queue[0]<now-seconds:
                queue.popleft()
            if len(queue)>=limit:
                return False
            queue.append(now)
            if len(self.items)>5000:
                self.items={k:v for k,v in self.items.items() if v and v[-1]>=now-seconds}
                self.items=defaultdict(deque,self.items)
            return True

def create_app(config=None):
    config=config or Config()
    @asynccontextmanager
    async def lifespan(app):
        config.prepare()
        app.state.config=config
        app.state.db=Database(config.data_dir/"convoy.sqlite3")
        app.state.auth=Auth(app.state.db,config)
        app.state.registry=ModelRegistry(config.model_dir,config.inference_threads)
        app.state.manager=JobManager(app.state.db,app.state.registry,config)
        app.state.upload_lock=threading.Lock()
        app.state.db.event("Service started")
        yield
        await run_in_threadpool(app.state.manager.close)

    app=FastAPI(title="MathTech Convoy Vision",version="1.0.0",lifespan=lifespan,
                docs_url=None,redoc_url=None,openapi_url=None)
    limiter=Limiter()

    @app.middleware("http")
    async def security(request,call_next):
        # Reject declared oversize uploads before multipart parsing. Nginx also enforces this.
        if request.method=="POST" and request.url.path=="/api/media":
            try:
                length=int(request.headers.get("content-length","0"))
            except ValueError:
                return JSONResponse({"detail":"Invalid Content-Length"},400)
            if length<=0:
                return JSONResponse({"detail":"Video uploads require Content-Length"},411)
            if length>(config.max_upload_mb+1)*1024*1024:
                return JSONResponse({"detail":f"Upload limit is {config.max_upload_mb} MB"},413)
            upload_user=app.state.auth.session(request.cookies.get("mt_session"))
            if not upload_user:
                return JSONResponse({"detail":"Sign in to upload"},401)
            if upload_user["role"] not in {"admin","operator"}:
                return JSONResponse({"detail":"Your role cannot upload videos"},403)
            if not hmac.compare_digest(request.headers.get("x-csrf-token",""),upload_user["csrf"]):
                return JSONResponse({"detail":"Session verification failed; refresh and sign in again"},403)
        if request.url.path.startswith("/api/"):
            ip=request.client.host if request.client else "unknown"
            limit=8 if request.url.path=="/api/auth/login" else 1800
            if not limiter.allow((ip,"login" if limit==8 else "api"),limit):
                return JSONResponse({"detail":"Too many requests; try again in one minute"},429,headers={"Retry-After":"60"})
        try:
            response=await call_next(request)
        except Exception:
            # Detailed exceptions stay in the server log; do not expose filesystem paths to clients.
            import logging
            logging.exception("Request failed")
            response=JSONResponse({"detail":"Server error. Check system logs and retry."},500)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="same-origin"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"]="no-store"
        return response

    def db():
        return app.state.db
    def manager():
        return app.state.manager
    def own(row,user):
        require_role(user,"admin","operator")
        if row["owner"]!=user["id"] and user["role"]!="admin":
            raise HTTPException(403,"Only the owner or an administrator can change this item")
    def get_media(mid):
        row=db().one("SELECT * FROM media WHERE id=?",(mid,))
        if not row:
            raise HTTPException(404,"Video not found")
        return row
    def get_job(jid):
        row=manager().job(jid)
        if not row:
            raise HTTPException(404,"Session not found")
        return row
    def media_frame(media,index=0):
        if index>=media["frame_count"]:
            raise HTTPException(422,"Frame index is outside the video")
        cap=cv2.VideoCapture(str(config.data_dir/"uploads"/media["filename"]))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,image=cap.read()
            if not ok:
                raise HTTPException(422,"Video frame could not be decoded")
            return image
        finally:
            cap.release()

    @app.get("/api/health")
    def health():
        return {"status":"ok","version":"1.0.0"}

    @app.get("/api/openapi.json")
    def api_schema(user=Depends(current_user)):
        return app.openapi()

    @app.post("/api/auth/login")
    def login(body:Login,request:Request):
        origin=request.headers.get("origin")
        allowed=config.public_origin or str(request.base_url).rstrip("/")
        if origin and origin!=allowed:
            raise HTTPException(403,"Sign in from the application origin")
        token,user=app.state.auth.login(body.username,body.password)
        response=JSONResponse(user)
        response.set_cookie("mt_session",token,max_age=config.session_hours*3600,httponly=True,
                            secure=config.secure_cookies,samesite="strict",path="/")
        return response

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.post("/api/auth/logout")
    def logout(request:Request,user=Depends(current_user)):
        db().execute("DELETE FROM auth_sessions WHERE token_hash=?",(token_hash(request.cookies.get("mt_session","")),))
        response=JSONResponse({"ok":True});response.delete_cookie("mt_session",path="/")
        return response

    @app.get("/api/users")
    def users(user=Depends(current_user)):
        require_role(user,"admin")
        return db().all("SELECT id,username,role,created FROM users ORDER BY created")

    @app.post("/api/users",status_code=201)
    def add_user(body:UserCreate,user=Depends(current_user)):
        require_role(user,"admin")
        uid=str(uuid.uuid4())
        try:
            db().execute("INSERT INTO users VALUES(?,?,?,?,?)",(uid,body.username,password_hash(body.password),body.role,time.time()))
        except sqlite3.IntegrityError:
            raise HTTPException(409,"Username already exists")
        db().event(f"Created {body.role} user {body.username}",actor=user["username"])
        return {"id":uid,"username":body.username,"role":body.role}

    @app.delete("/api/users/{uid}")
    def delete_user(uid:str,user=Depends(current_user)):
        require_role(user,"admin")
        target=db().one("SELECT * FROM users WHERE id=?",(uid,))
        if not target:
            raise HTTPException(404,"User not found")
        if uid==user["id"] or target["role"]=="admin":
            raise HTTPException(409,"Administrator accounts cannot be deleted here")
        # Keep historical audit/job foreign keys; remove access and mark the username disabled instead.
        db().execute("DELETE FROM auth_sessions WHERE user_id=?",(uid,))
        db().execute("UPDATE users SET password_hash=? WHERE id=?",(password_hash(secrets.token_urlsafe(64)),uid))
        db().event(f"Revoked access for {target['username']}",actor=user["username"])
        return {"ok":True}

    @app.get("/api/settings")
    def settings(user=Depends(current_user)):
        return db().settings()

    @app.put("/api/settings")
    def update_settings(body:Settings,user=Depends(current_user)):
        require_role(user,"admin")
        data=body.model_dump()
        db().execute("UPDATE settings SET data=? WHERE id=1",(json.dumps(data),))
        db().event("Default settings updated",actor=user["username"])
        return data

    @app.get("/api/models")
    def models(user=Depends(current_user)):
        return app.state.registry.list()

    @app.post("/api/models/{model_id}/verify")
    def verify_model(model_id:str,user=Depends(current_user)):
        require_role(user,"admin","operator")
        try:
            model=app.state.registry.get(model_id)
            t=time.perf_counter()
            model.predict(np.zeros((320,320,3),np.uint8),segment=model.item["task"]=="segment")
            return {"ok":True,"provider":"CPUExecutionProvider","warmup_ms":round((time.perf_counter()-t)*1000,1),"supported_classes":sorted(VEHICLES)}
        except ValueError as exc:
            raise HTTPException(422,str(exc))

    @app.get("/api/media")
    def list_media(user=Depends(current_user)):
        return db().all("SELECT m.*,a.updated AS annotated_at FROM media m LEFT JOIN annotations a ON a.media_id=m.id ORDER BY m.created DESC LIMIT 1000")

    @app.post("/api/media",status_code=201)
    def upload(file:UploadFile=File(...),user=Depends(current_user)):
        require_role(user,"admin","operator")
        name=Path((file.filename or "video").replace("\\","/")).name[:160]
        suffix=Path(name).suffix.lower()
        if suffix not in {".mp4",".mov",".mkv",".avi",".webm",".m4v"}:
            raise HTTPException(415,"Use MP4, MOV, MKV, AVI or WebM video")
        mid=str(uuid.uuid4());filename=mid+suffix;path=config.data_dir/"uploads"/filename
        # Serialize writes to make quota accounting atomic within the supported single process.
        with app.state.upload_lock:
            try:
                initial=storage_bytes(config.data_dir);size=0;digest=hashlib.sha256()
                with path.open("wb") as out:
                    for chunk in iter(lambda:file.file.read(1024*1024),b""):
                        size+=len(chunk)
                        if size>config.max_upload_mb*1024*1024:
                            raise HTTPException(413,f"Upload limit is {config.max_upload_mb} MB")
                        if initial+size>config.max_storage_mb*1024*1024:
                            raise HTTPException(507,"Storage quota reached")
                        digest.update(chunk);out.write(chunk)
                cap=cv2.VideoCapture(str(path))
                try:
                    fps=float(cap.get(cv2.CAP_PROP_FPS));count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    ok,image=cap.read()
                    if not ok or not np.isfinite(fps) or fps<=0 or count<=0:
                        raise HTTPException(422,"Video is empty, corrupt or unsupported by this decoder")
                    h,w=image.shape[:2]
                    if h*w>3840*2160*1.05 or min(h,w)<16:
                        raise HTTPException(422,"Use videos up to 3840×2160 and at least 16×16")
                finally:
                    cap.release()
                db().execute("INSERT INTO media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(mid,name,filename,digest.hexdigest(),size,w,h,fps,count,count/fps,time.time(),user["id"]))
                db().event(f"Uploaded video: {name}",actor=user["username"])
                return get_media(mid)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            finally:
                file.file.close()

    @app.get("/api/media/{mid}/frame.jpg")
    def preview(mid:str,frame_index:int=0,user=Depends(current_user)):
        if frame_index<0:
            raise HTTPException(422,"Frame index must be nonnegative")
        return Response(jpeg(media_frame(get_media(mid),frame_index)),media_type="image/jpeg")

    @app.delete("/api/media/{mid}")
    def delete_media(mid:str,user=Depends(current_user)):
        media=get_media(mid);own(media,user)
        if db().one("SELECT id FROM jobs WHERE media_id=? LIMIT 1",(mid,)):
            raise HTTPException(409,"Delete sessions that reference this video first")
        db().execute("DELETE FROM media WHERE id=?",(mid,))
        (config.data_dir/"uploads"/media["filename"]).unlink(missing_ok=True)
        return {"ok":True}

    @app.get("/api/jobs")
    def list_jobs(user=Depends(current_user)):
        return db().all("SELECT j.id,j.name,j.source,j.status,j.created,j.updated,j.error,j.owner,j.media_id,(SELECT COUNT(*) FROM frames f WHERE f.job_id=j.id) AS analyzed_frames FROM jobs j ORDER BY j.created DESC LIMIT 1000")

    @app.post("/api/jobs",status_code=201)
    def create_job(body:JobCreate,user=Depends(current_user)):
        require_role(user,"admin","operator")
        try:
            return manager().create(body,user)
        except ValueError as exc:
            raise HTTPException(422,str(exc))

    @app.get("/api/jobs/{jid}")
    def job(jid:str,user=Depends(current_user)):
        return get_job(jid)

    @app.post("/api/jobs/{jid}/control")
    def control(jid:str,body:Control,user=Depends(current_user)):
        own(get_job(jid),user)
        try:
            return manager().control(jid,body.action)
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    @app.delete("/api/jobs/{jid}")
    def delete_job(jid:str,user=Depends(current_user)):
        own(get_job(jid),user)
        try:
            manager().delete(jid)
        except ValueError as exc:
            raise HTTPException(409,str(exc))
        return {"ok":True}

    @app.get("/api/jobs/{jid}/result")
    def result(jid:str,seq:int|None=None,user=Depends(current_user)):
        get_job(jid)
        if seq is not None and seq<0:
            raise HTTPException(422,"Sequence must be nonnegative")
        return {"frame":manager().result(jid,seq)}

    @app.get("/api/jobs/{jid}/frames/{seq}/{view}.jpg")
    def frame(jid:str,seq:int,view:str,user=Depends(current_user)):
        get_job(jid)
        if seq<0 or view not in {"original","overlay","mask","trail"}:
            raise HTTPException(422,"Invalid frame or view")
        content=manager().frame(jid,seq,view)
        if content is None:
            raise HTTPException(404,"Frame is not available")
        return Response(content,media_type="image/jpeg")

    @app.get("/api/jobs/{jid}/summary")
    def summary(jid:str,user=Depends(current_user)):
        get_job(jid)
        return manager().summary(jid)

    @app.get("/api/jobs/{jid}/export/{kind}")
    def export(jid:str,kind:str,user=Depends(current_user)):
        job=get_job(jid)
        if kind not in {"json","csv"}:
            raise HTTPException(422,"Use json or csv")
        def generate():
            with db().connect() as connection:
                rows=connection.execute("SELECT result FROM frames WHERE job_id=? ORDER BY seq",(jid,))
                if kind=="json":
                    yield '{"job":'+json.dumps(job)+',"frames":['
                    first=True
                    for row in rows:
                        yield ("" if first else ",")+row["result"];first=False
                    yield "]}"
                else:
                    buffer=io.StringIO();writer=csv.writer(buffer)
                    writer.writerow(["seq","timestamp_s","track_id","class","confidence","x1","y1","x2","y2","center_x_px","center_y_px","mask_area_px","bbox_area_px","speed_px_s","direction_image_deg","inference_ms"])
                    yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
                    for row in rows:
                        r=json.loads(row["result"])
                        for obj in r["objects"]:
                            writer.writerow([r["seq"],r["timestamp"],obj["id"],obj["class_name"],obj["confidence"],*obj["bbox"],*obj["center"],obj["mask_area_px"],obj["bbox_area_px"],obj["velocity"]["speed"],obj["direction_image_deg"],r["inference_ms"]])
                        yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
        return StreamingResponse(generate(),media_type="application/json" if kind=="json" else "text/csv",
                                 headers={"Content-Disposition":f'attachment; filename="mathtech-{jid[:8]}.{kind}"'})

    @app.get("/api/media/{mid}/annotations")
    def get_annotations(mid:str,frame_index:int=0,user=Depends(current_user)):
        media=get_media(mid)
        if frame_index<0 or frame_index>=media["frame_count"]:
            raise HTTPException(422,"Invalid source frame")
        row=db().one("SELECT data FROM annotations WHERE media_id=?",(mid,))
        data=json.loads(row["data"]) if row else {}
        return {"frame_index":frame_index,"polygons":data.get(str(frame_index),[]),"annotated_frames":sorted(map(int,data))}

    @app.put("/api/media/{mid}/annotations")
    def save_annotations(mid:str,body:Annotation,frame_index:int=0,user=Depends(current_user)):
        media=get_media(mid);own(media,user)
        if frame_index<0 or frame_index>=media["frame_count"]:
            raise HTTPException(422,"Invalid source frame")
        for polygon in body.polygons:
            if any(not (0<=x<=1 and 0<=y<=1) for x,y in polygon.points):
                raise HTTPException(422,"Polygon coordinates must be normalized between 0 and 1")
        with db().connect() as connection:
            row=connection.execute("SELECT data FROM annotations WHERE media_id=?",(mid,)).fetchone()
            data=json.loads(row["data"]) if row else {}
            data[str(frame_index)]=[p.model_dump() for p in body.polygons]
            if len(data)>1000:
                raise HTTPException(422,"Maximum 1000 annotated frames per source video")
            connection.execute("INSERT INTO annotations VALUES(?,?,?) ON CONFLICT(media_id) DO UPDATE SET data=excluded.data,updated=excluded.updated",(mid,json.dumps(data),time.time()))
        db().event(f"Saved annotations: {media['name']} frame {frame_index}",actor=user["username"])
        return {"ok":True}

    @app.get("/api/dataset/export")
    def dataset_export(user=Depends(current_user)):
        require_role(user,"admin","operator")
        rows=db().all("SELECT m.*,a.data FROM media m JOIN annotations a ON a.media_id=m.id ORDER BY m.sha256")
        if not rows:
            raise HTTPException(422,"Annotate at least one video frame first")
        labels=["car","bus","truck","motorcycle","bicycle"]
        # Split by source content hash: duplicate videos cannot leak across train/val.
        hashes=sorted({r["sha256"] for r in rows},key=lambda x:hashlib.sha256(("42"+x).encode()).hexdigest())
        val=set(hashes[:max(1,len(hashes)//5)]) if len(hashes)>1 else set()
        spool=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
        try:
            with zipfile.ZipFile(spool,"w",zipfile.ZIP_DEFLATED) as archive:
                manifest=[];total=0
                for media in rows:
                    for index,polygons in json.loads(media["data"]).items():
                        if total>=1000:
                            raise HTTPException(422,"Export limit is 1000 frames; export a smaller reviewed dataset")
                        split="val" if media["sha256"] in val else "train"
                        stem=f"{media['id']}_{index}"
                        archive.writestr(f"images/{split}/{stem}.jpg",jpeg(media_frame(media,int(index))))
                        lines=[]
                        for p in polygons:
                            coords=" ".join(f"{n:.6f}" for point in p["points"] for n in point)
                            lines.append(f"{labels.index(p['label'])} {coords}")
                        archive.writestr(f"labels/{split}/{stem}.txt","\n".join(lines)+("\n" if lines else ""))
                        manifest.append({"image":stem+".jpg","source_sha256":media["sha256"],"frame":int(index),"split":split})
                        total+=1
                archive.writestr("data.yaml","# Set path to this dataset's absolute directory before training\npath: .\ntrain: images/train\nval: images/val\nnames:\n"+"\n".join(f"  {i}: {name}" for i,name in enumerate(labels))+"\n")
                archive.writestr("manifest.json",json.dumps(manifest,indent=2))
                archive.writestr("README.txt","Human-reviewed vehicle segmentation polygons. Split seed 42 at source-video SHA-256 level. With a single source, validation is empty; add independent videos before evaluation. Duplicate/transcoded scenes require manual grouping to avoid leakage.\n")
            spool.seek(0)
            def stream():
                try:
                    for chunk in iter(lambda:spool.read(1024*1024),b""):
                        yield chunk
                finally:
                    spool.close()
            return StreamingResponse(stream(),media_type="application/zip",headers={"Content-Disposition":'attachment; filename="MathTech-Vehicle-Dataset.zip"'})
        except BaseException:
            spool.close();raise

    @app.get("/api/events")
    def events(level:str="ALL",user=Depends(current_user)):
        if level not in {"ALL","INFO","WARN","ERROR"}:
            raise HTTPException(422,"Invalid log filter")
        return db().all("SELECT * FROM events"+(" WHERE level=?" if level!="ALL" else "")+" ORDER BY id DESC LIMIT 300",(level,) if level!="ALL" else ())

    @app.get("/api/system")
    def system(user=Depends(current_user)):
        try:
            load=list(os.getloadavg())
        except (AttributeError,OSError):
            load=None
        usage=storage_bytes(config.data_dir)
        active=sum(r.status in ("running","paused") for r in manager().runtimes.values())
        return {"backend":"online","database":"SQLite / WAL","model_provider":"ONNX Runtime / CPU",
          "cpu_load":load,"active_jobs":active,"max_jobs":config.max_jobs,"storage_mb":round(usage/1024**2,2),
          "max_storage_mb":config.max_storage_mb,"max_upload_mb":config.max_upload_mb,"max_analyzed_frames":config.max_frames,
          "max_live_seconds":config.max_live_seconds,"version":"1.0.0"}

    async def ws_user(ws):
        user=app.state.auth.session(ws.cookies.get("mt_session"))
        origin=ws.headers.get("origin")
        allowed=config.public_origin or ("https" if ws.url.scheme=="wss" else "http")+"://"+ws.headers.get("host","")
        if not user or (origin and origin!=allowed):
            await ws.close(code=1008);return None
        await ws.accept()
        return user

    @app.websocket("/ws/jobs/{jid}")
    async def updates(ws:WebSocket,jid:str):
        user=await ws_user(ws)
        if not user:
            return
        seq,status=-1,None
        try:
            while True:
                job=await run_in_threadpool(manager().job,jid)
                if not job:
                    await ws.send_json({"error":"Session not found"});break
                frame=await run_in_threadpool(manager().result,jid)
                current=frame["seq"] if frame else -1
                if current!=seq or job["status"]!=status:
                    await ws.send_json({"job":job,"frame":frame})
                    seq,status=current,job["status"]
                if job["status"] not in {"running","paused"}:
                    break
                if not app.state.auth.session(ws.cookies.get("mt_session")):
                    await ws.close(code=1008);break
                await asyncio.sleep(.35)
        except (WebSocketDisconnect,RuntimeError):
            pass
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    @app.websocket("/ws/live/{jid}")
    async def live(ws:WebSocket,jid:str):
        user=await ws_user(ws)
        if not user:
            return
        job=await run_in_threadpool(manager().job,jid)
        if not job or job["source"]!="camera" or (job["owner"]!=user["id"] and user["role"]!="admin") or user["role"]=="viewer":
            await ws.close(code=1008);return
        try:
            hello=await asyncio.wait_for(ws.receive_json(),10)
            if not hmac.compare_digest(str(hello.get("csrf","")),user["csrf"]):
                await ws.close(code=1008);return
            await ws.send_json({"ready":True})
            while True:
                data=await asyncio.wait_for(ws.receive_bytes(),35)
                if not app.state.auth.session(ws.cookies.get("mt_session")):
                    await ws.close(code=1008);break
                if len(data)>4*1024*1024:
                    await ws.close(code=1009);break
                # Validate JPEG SOF dimensions before allocation/decoding to reject pixel bombs.
                width,height=jpeg_dimensions(data)
                if width*height>1920*1080 or min(width,height)<16:
                    raise ValueError("Live frames must be JPEG up to 1920×1080")
                image=await run_in_threadpool(cv2.imdecode,np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("Invalid JPEG frame")
                frame=await run_in_threadpool(manager().process_live,jid,image)
                await ws.send_json({"frame":frame,"job":await run_in_threadpool(manager().job,jid)})
                runtime=manager().runtimes.get(jid)
                if not runtime or runtime.stop.is_set():
                    break
        except (WebSocketDisconnect,asyncio.TimeoutError):
            runtime=manager().runtimes.get(jid)
            if runtime:
                runtime.gate.clear();runtime.status="paused"
                db().execute("UPDATE jobs SET status='paused',updated=? WHERE id=?",(time.time(),jid))
        except (ValueError,RuntimeError) as exc:
            runtime=manager().runtimes.get(jid)
            if runtime:
                manager().finish(runtime,"failed",str(exc)[:300])
            try:
                await ws.send_json({"error":str(exc)[:300]})
            except RuntimeError:
                pass
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    app.mount("/static",StaticFiles(directory=ROOT/"frontend"),name="static")
    @app.get("/")
    def index():
        return FileResponse(ROOT/"frontend"/"index.html")
    return app

def jpeg_dimensions(data):
    """Parse JPEG frame header before decoding; a bounded scan avoids decompression bombs."""
    if len(data)<4 or data[:2]!=b"\xff\xd8":
        raise ValueError("Expected JPEG frame")
    i=2
    while i+4<=min(len(data),262144):
        if data[i]!=255:
            raise ValueError("Malformed JPEG header")
        while i<len(data) and data[i]==255:
            i+=1
        if i>=len(data):
            break
        marker=data[i];i+=1
        if marker in {0xD8,0xD9} or 0xD0<=marker<=0xD7:
            continue
        length=int.from_bytes(data[i:i+2],"big")
        if length<2 or i+length>len(data):
            break
        if marker in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF} and length>=7:
            return int.from_bytes(data[i+5:i+7],"big"),int.from_bytes(data[i+3:i+5],"big")
        if marker==0xDA:
            break
        i+=length
    raise ValueError("JPEG dimensions could not be validated")

app=create_app()
