"""Create a coherent database/media backup after stopping the server."""
from pathlib import Path
import argparse
import sqlite3
import tempfile
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir',type=Path,default=Path('data'))
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
data=args.data_dir.resolve();output=args.output.resolve()
if output.is_relative_to(data):
    raise SystemExit('Save backups outside DATA_DIR')
if output.exists():
    raise SystemExit('Backup path already exists; choose a new filename')
if not (data/'convoy.sqlite3').exists():
    raise SystemExit('Database not found')
output.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temporary:
    snapshot=Path(temporary)/'convoy.sqlite3'
    with sqlite3.connect(data/'convoy.sqlite3') as source,sqlite3.connect(snapshot) as dest:
        if source.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('running','paused')").fetchone()[0]:
            raise SystemExit('Stop active runs and the server before backup')
        source.backup(dest)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot,'data/convoy.sqlite3')
        for directory in ['uploads','captures']:
            for file in (data/directory).rglob('*'):
                if file.is_file() and not file.is_symlink():
                    archive.write(file,'data/'+file.relative_to(data).as_posix())
print('Backup saved:',output)

