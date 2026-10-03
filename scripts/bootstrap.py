"""Create an isolated runtime, prompt for first admin password and start locally."""
from pathlib import Path
import getpass
import hashlib
import os
import sqlite3
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if not (3,11)<=sys.version_info[:2]<=(3,13):
    sys.exit("Install Python 3.12 (supported: 3.11–3.13), then run this launcher again.")

def load_env():
    path=ROOT/".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            key,separator,value=line.partition('=')
            if separator and key.strip():
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))

load_env()
runtime=ROOT/".venv"
python=runtime/("Scripts/python.exe" if os.name=="nt" else "bin/python")
if not python.exists():
    print("Creating the Python runtime…")
    venv.create(runtime,with_pip=True)
stamp=runtime/".requirements.sha256"
fingerprint=hashlib.sha256((ROOT/"requirements.txt").read_bytes()+(ROOT/"constraints.txt").read_bytes()).hexdigest()
if not stamp.exists() or stamp.read_text()!=fingerprint:
    print("Installing pinned runtime dependencies (internet needed on first setup)…")
    subprocess.run([str(python),"-m","pip","install","-r","requirements.txt"],check=True)
    stamp.write_text(fingerprint)
database=Path(os.getenv("DATA_DIR",str(ROOT/"data")))/"convoy.sqlite3"
has_user=False
if database.exists():
    with sqlite3.connect(database) as connection:
        has_user=bool(connection.execute("SELECT id FROM users LIMIT 1").fetchone())
if not has_user and not os.getenv("ADMIN_PASSWORD"):
    print("Create your administrator password. Username: "+os.getenv('ADMIN_USER','admin'))
    while True:
        password=getpass.getpass("Password (at least 12 characters): ")
        if len(password)<12:
            print("Use at least 12 characters.");continue
        if password!=getpass.getpass("Repeat password: "):
            print("Passwords do not match.");continue
        os.environ['ADMIN_PASSWORD']=password;break
host=os.getenv("HOST","127.0.0.1");port=os.getenv("PORT","8000")
print(f"Open http://localhost:{port} — press Ctrl+C to stop.")
try:
    subprocess.run([str(python),"-m","uvicorn","backend.app:app","--host",host,"--port",port,
                    "--workers","1","--ws-max-size","4194304","--timeout-graceful-shutdown","30"],check=True)
except KeyboardInterrupt:
    pass
