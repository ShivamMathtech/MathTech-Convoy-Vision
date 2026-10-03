"""Integration tests exercise actual codecs, ONNX inference and persistence."""
import io
import json
from pathlib import Path
import time
import zipfile
import cv2
import numpy as np
import pytest
from backend.app import jpeg_dimensions, create_app
from backend.config import Config
from backend.db import Database
from backend.schemas import JobCreate
from backend.tracking import Tracker, group_status
from backend.vision import ModelRegistry, letterbox, paint

ROOT=Path(__file__).resolve().parents[1]

def upload(client,clip):
    with clip.open('rb') as f:
        response=client.post('/api/media',files={'file':(clip.name,f,'video/x-msvideo')})
    assert response.status_code==201,response.text
    return response.json()

def complete(client,jid):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] not in ('running','paused'):
            assert job['status']=='completed',job
            return job
        time.sleep(.04)
    pytest.fail('Analysis worker timed out')

def test_auth_csrf_and_roles(client):
    assert client.get('/api/jobs').status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':'Testing-password-2026'},headers={'Origin':'https://untrusted.example'}).status_code==403
    user=client.post('/api/auth/login',json={'username':'admin','password':'Testing-password-2026'}).json()
    assert client.put('/api/settings',json={}).status_code==403
    client.headers['X-CSRF-Token']=user['csrf']
    assert client.post('/api/users',json={'username':'viewer','password':'Viewer-password-2026','role':'viewer'}).status_code==201
    viewer=client.post('/api/auth/login',json={'username':'viewer','password':'Viewer-password-2026'}).json()
    client.headers['X-CSRF-Token']=viewer['csrf']
    assert client.get('/api/models').status_code==200
    assert client.put('/api/settings',json={}).status_code==403
    assert client.post('/api/jobs',json={}).status_code==403
    assert client.post('/api/media',files={'file':('viewer.mp4',b'not decoded')}).status_code==403
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me').status_code==401

def test_video_analysis_replay_exports_and_cleanup(admin,clip):
    media=upload(admin,clip)
    assert media['frame_count']==10
    assert admin.get(f"/api/media/{media['id']}/frame.jpg").headers['content-type']=='image/jpeg'
    response=admin.post('/api/jobs',json={'media_id':media['id'],'analysis_fps':5,'mode':'segment','name':'Integration run'})
    assert response.status_code==201,response.text
    jid=response.json()['id'];job=complete(admin,jid)
    assert job['analyzed_frames']==5
    frame=admin.get(f'/api/jobs/{jid}/result?seq=0').json()['frame']
    assert frame['mode']=='segment' and frame['coordinate_space']=='analysis_image_pixels'
    for view in ('overlay','mask','original','trail'):
        content=admin.get(f'/api/jobs/{jid}/frames/0/{view}.jpg')
        assert content.status_code==200
        assert cv2.imdecode(np.frombuffer(content.content,np.uint8),cv2.IMREAD_COLOR).shape[:2]==(240,320)
    summary=admin.get(f'/api/jobs/{jid}/summary').json()
    assert summary['analyzed_frames']==5 and len(summary['series'])==5
    exported=admin.get(f'/api/jobs/{jid}/export/json').json()
    assert exported['job']['id']==jid and len(exported['frames'])==5
    assert admin.get(f'/api/jobs/{jid}/export/csv').text.startswith('seq,timestamp_s,track_id')
    assert admin.delete(f"/api/media/{media['id']}").status_code==409
    assert admin.post(f'/api/jobs/{jid}/control',json={'action':'resume'}).status_code==409
    assert admin.delete(f'/api/jobs/{jid}').status_code==200
    assert admin.delete(f"/api/media/{media['id']}").status_code==200

def test_validation_and_upload_limits(admin):
    assert admin.post('/api/media',files={'file':('no.txt',b'123')}).status_code==415
    assert admin.post('/api/media',files={'file':('corrupt.mp4',b'not a video')}).status_code==422
    assert admin.post('/api/media',files={'file':('large.mp4',b'x'*(5*1024**2+100))}).status_code==413
    assert not list((admin.app.state.config.data_dir/'uploads').iterdir())
    assert admin.post('/api/jobs',json={'media_id':'missing'}).status_code==422
    assert admin.post('/api/jobs',json={'analysis_fps':100}).status_code==422
    assert admin.get('/api/events?level=invalid').status_code==422

def test_annotation_dataset_roundtrip(admin,clip):
    media=upload(admin,clip);mid=media['id']
    polygon={'label':'car','points':[[.1,.2],[.5,.2],[.5,.6],[.1,.6]]}
    assert admin.put(f'/api/media/{mid}/annotations?frame_index=0',json={'polygons':[polygon]}).status_code==200
    assert admin.put(f'/api/media/{mid}/annotations?frame_index=2',json={'polygons':[]}).status_code==200
    got=admin.get(f'/api/media/{mid}/annotations').json()
    assert got['polygons'][0]['label']=='car' and got['annotated_frames']==[0,2]
    invalid={**polygon,'points':[[2.,.1],[.1,.2],[.2,.3]]}
    assert admin.put(f'/api/media/{mid}/annotations',json={'polygons':[invalid]}).status_code==422
    response=admin.get('/api/dataset/export')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert 'data.yaml' in z.namelist()
        assert len([x for x in z.namelist() if x.endswith('.jpg')])==2
        assert z.read(f'labels/train/{mid}_0.txt').decode().startswith('0 0.100000')
        assert len(json.loads(z.read('manifest.json')))==2

def test_model_masks_are_neural_and_not_boxes():
    registry=ModelRegistry(ROOT/'models')
    model=registry.get('yolov8n-seg')
    image=cv2.imread(str(ROOT/'samples'/'vehicle-validation.jpg'))
    assert image is not None
    objects=model.predict(image)
    buses=[o for o in objects if o['class_name']=='bus']
    assert buses and buses[0]['confidence']>.7
    obj=buses[0]
    assert obj['mask_area_px']>1000 and obj['mask_area_px']<obj['bbox_area_px']*.95
    assert sum(len(c['points']) for c in obj['contours'])>10
    assert all(o['class_name'] in {'car','bus','truck','motorcycle','bicycle'} for o in objects)
    assert all(o['mask_area_px'] is None for o in model.predict(image,segment=False))
    assert paint(image,{'objects':objects},'mask').shape==image.shape

def test_model_checksum_rejection(tmp_path):
    data=json.loads((ROOT/'models'/'registry.json').read_text())
    data['models'][0]['sha256']='0'*64
    (tmp_path/'registry.json').write_text(json.dumps(data))
    (tmp_path/'yolov8n-seg.onnx').write_bytes(b'wrong')
    with pytest.raises(ValueError,match='checksum'):
        ModelRegistry(tmp_path).get('yolov8n-seg')

def test_tracker_timestamps_occlusion_and_motion():
    tracker=Tracker(trail=4)
    def detection(x):
        return {'class_name':'car','bbox':[x,20,x+30,45],'center':[x+15,32.5],'confidence':.9}
    first=tracker.update([detection(0)],0,320,240)[0]
    second=tracker.update([detection(10)],1,320,240)[0]
    assert first['id']==second['id'] and second['velocity']['speed']==pytest.approx(10)
    assert second['direction_image_deg']==0
    tracker.update([],1.5,320,240)
    assert tracker.update([detection(15)],2,320,240)[0]['id']==first['id']
    assert tracker.update([detection(15)],5,320,240)[0]['id']!=first['id']

def test_group_is_explicit_heuristic():
    objs=[{'id':i,'center':[60+i*30,70],'velocity':{'x':10,'y':0},'hits':4} for i in range(3)]
    result=group_status(objs,320,240)
    assert result['candidate'] and result['size']==3
    objs[1]['velocity']={'x':-10,'y':0}
    assert not group_status(objs,320,240)['candidate']

def test_live_websocket_real_jpeg_and_replay(admin):
    response=admin.post('/api/jobs',json={'source':'camera','name':'Live integration'})
    assert response.status_code==201,response.text
    jid=response.json()['id']
    encoded=cv2.imencode('.jpg',np.full((240,320,3),40,np.uint8))[1].tobytes()
    time.sleep(.21)
    with admin.websocket_connect(f'/ws/live/{jid}') as ws:
        ws.send_json({'csrf':admin.headers['X-CSRF-Token']});assert ws.receive_json()['ready']
        ws.send_bytes(encoded);response=ws.receive_json();assert response['frame']['seq']==0
        assert admin.get(f'/api/jobs/{jid}/frames/0/overlay.jpg').status_code==200
        assert admin.post(f'/api/jobs/{jid}/control',json={'action':'pause'}).status_code==200
        ws.send_bytes(encoded);assert ws.receive_json()['frame'] is None
        assert admin.post(f'/api/jobs/{jid}/control',json={'action':'resume'}).status_code==200
        assert admin.post(f'/api/jobs/{jid}/control',json={'action':'stop'}).status_code==200
        ws.send_bytes(encoded)
    assert admin.get(f'/api/jobs/{jid}/frames/0/mask.jpg').status_code==200

def test_jpeg_header_guard():
    image=np.zeros((33,75,3),np.uint8)
    encoded=cv2.imencode('.jpg',image)[1].tobytes()
    assert jpeg_dimensions(encoded)==(75,33)
    with pytest.raises(ValueError):
        jpeg_dimensions(b'invalid')

def test_restart_recovers_active_sessions(tmp_path):
    db=Database(tmp_path/'test.db')
    db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",('id','name',None,'camera','running','{}',1,1,None,None))
    Database(tmp_path/'test.db')
    assert db.one('SELECT status FROM jobs')['status']=='interrupted'

def test_file_updates_socket_final_state(admin,clip):
    media=upload(admin,clip)
    jid=admin.post('/api/jobs',json={'media_id':media['id']}).json()['id']
    complete(admin,jid)
    with admin.websocket_connect('/ws/jobs/'+jid) as ws:
        payload=ws.receive_json()
        assert payload['job']['status']=='completed' and payload['frame']['seq']==4
