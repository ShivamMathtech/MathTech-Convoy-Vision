"""Explicit, environment driven single-node deployment configuration."""
from dataclasses import dataclass, field
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT / "data")).resolve())
    model_dir: Path = field(default_factory=lambda: Path(os.getenv("MODEL_DIR", ROOT / "models")).resolve())
    admin_user: str = field(default_factory=lambda: os.getenv("ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    secure_cookies: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    public_origin: str = field(default_factory=lambda: os.getenv("PUBLIC_ORIGIN", ""))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "512")))
    max_storage_mb: int = field(default_factory=lambda: int(os.getenv("MAX_STORAGE_MB", "10240")))
    max_jobs: int = field(default_factory=lambda: int(os.getenv("MAX_ACTIVE_JOBS", "2")))
    max_frames: int = field(default_factory=lambda: int(os.getenv("MAX_ANALYZED_FRAMES", "30000")))
    max_live_seconds: int = field(default_factory=lambda: int(os.getenv("MAX_LIVE_SECONDS", "3600")))
    inference_threads: int = field(default_factory=lambda: int(os.getenv("INFERENCE_THREADS", "2")))
    session_hours: int = 12

    def prepare(self):
        if not 1 <= self.max_jobs <= 8:
            raise ValueError("MAX_ACTIVE_JOBS must be 1..8")
        for directory in (self.data_dir, self.data_dir / "uploads", self.data_dir / "captures"):
            directory.mkdir(parents=True, exist_ok=True)

