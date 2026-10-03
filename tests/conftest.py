from pathlib import Path
import sys
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app import create_app
from backend.config import Config

@pytest.fixture
def client(tmp_path):
    app=create_app(Config(data_dir=tmp_path/"data",model_dir=ROOT/"models",admin_password="Testing-password-2026",max_upload_mb=4,max_jobs=1))
    with TestClient(app) as client:
        yield client

@pytest.fixture
def admin(client):
    response=client.post('/api/auth/login',json={'username':'admin','password':'Testing-password-2026'})
    assert response.status_code==200
    client.headers['X-CSRF-Token']=response.json()['csrf']
    return client

@pytest.fixture
def clip(tmp_path):
    path=tmp_path/'test.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(320,240))
    assert writer.isOpened()
    for i in range(10):
        frame=np.full((240,320,3),40,np.uint8)
        cv2.rectangle(frame,(15+i*2,100),(70+i*2,150),(240,240,240),-1)
        writer.write(frame)
    writer.release()
    return path

