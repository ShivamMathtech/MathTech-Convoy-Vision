"""SQLite WAL persistence. Connections are short-lived and safe across worker threads."""
import contextlib
import json
import sqlite3
from pathlib import Path
import time

DEFAULTS = {"confidence": 0.30, "iou": 0.50, "analysis_fps": 5.0,
            "trail_length": 40, "mask_opacity": 0.48, "min_group": 3,
            "group_radius": 0.35, "show_labels": True}

class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
              created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL
              REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, name TEXT NOT NULL, filename TEXT NOT NULL,
              sha256 TEXT NOT NULL, size INTEGER NOT NULL, width INTEGER, height INTEGER, fps REAL,
              frame_count INTEGER, duration REAL, created REAL NOT NULL, owner TEXT REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, name TEXT NOT NULL, media_id TEXT
              REFERENCES media(id), source TEXT NOT NULL, status TEXT NOT NULL, config TEXT NOT NULL,
              created REAL NOT NULL, updated REAL NOT NULL, error TEXT, owner TEXT REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS frames(job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              seq INTEGER NOT NULL, source_frame INTEGER NOT NULL, timestamp REAL NOT NULL, result TEXT NOT NULL,
              PRIMARY KEY(job_id,seq));
            CREATE INDEX IF NOT EXISTS frames_time ON frames(job_id,timestamp);
            CREATE TABLE IF NOT EXISTS annotations(media_id TEXT PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
              data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
              level TEXT NOT NULL, message TEXT NOT NULL, job_id TEXT, actor TEXT);
            PRAGMA user_version=1;
            ''')
            c.execute("INSERT OR IGNORE INTO settings VALUES(1,?)", (json.dumps(DEFAULTS),))
            c.execute("UPDATE jobs SET status='interrupted',error='Service restarted; create a new run or replay saved frames.',updated=? WHERE status IN ('running','paused','queued')", (time.time(),))
            c.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))

    @contextlib.contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def all(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.connect() as c:
            r = c.execute(sql, args).fetchone()
            return dict(r) if r else None

    def execute(self, sql, args=()):
        with self.connect() as c:
            return c.execute(sql, args).rowcount

    def event(self, message, level="INFO", job_id=None, actor=None):
        self.execute("INSERT INTO events(created,level,message,job_id,actor) VALUES(?,?,?,?,?)",
                     (time.time(), level, message, job_id, actor))

    def settings(self):
        return json.loads(self.one("SELECT data FROM settings WHERE id=1")["data"])

