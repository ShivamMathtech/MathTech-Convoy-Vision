"""Local administrator password recovery; run with the server stopped."""
from pathlib import Path
import argparse
import getpass
import os
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.auth import password_hash

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir',type=Path,default=Path(os.getenv('DATA_DIR','data')))
parser.add_argument('--username',default='admin')
args=parser.parse_args()
database=args.data_dir/'convoy.sqlite3'
if not database.exists():
    sys.exit('Database not found; use the configured DATA_DIR')
password=getpass.getpass('New password (at least 12 characters): ')
if len(password)<12 or password!=getpass.getpass('Repeat password: '):
    sys.exit('Passwords must match and have at least 12 characters')
with sqlite3.connect(database) as c:
    user=c.execute('SELECT id FROM users WHERE username=?',(args.username,)).fetchone()
    if not user:
        sys.exit('User not found')
    c.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(password),user[0]))
    c.execute('DELETE FROM auth_sessions WHERE user_id=?',(user[0],))
print('Password updated; previous sessions revoked')

