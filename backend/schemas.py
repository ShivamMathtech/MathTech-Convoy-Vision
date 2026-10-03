from typing import Literal
from pydantic import BaseModel, Field

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)

class UserCreate(Login):
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "operator", "viewer"] = "operator"

class Settings(BaseModel):
    confidence: float = Field(default=.30, ge=.05, le=.95)
    iou: float = Field(default=.50, ge=.1, le=.9)
    analysis_fps: float = Field(default=5, ge=.5, le=15)
    trail_length: int = Field(default=40, ge=0, le=100)
    mask_opacity: float = Field(default=.48, ge=.1, le=.9)
    min_group: int = Field(default=3, ge=2, le=20)
    group_radius: float = Field(default=.35, ge=.05, le=.7)
    show_labels: bool = True

class JobCreate(Settings):
    media_id: str | None = None
    name: str = Field(default="Vehicle analysis", min_length=1, max_length=100)
    model_id: str = Field(default="yolov8n-seg", max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    mode: Literal["segment", "detect"] = "segment"
    source: Literal["file", "camera"] = "file"

class Control(BaseModel):
    action: Literal["pause", "resume", "stop"]

class Polygon(BaseModel):
    label: Literal["car", "bus", "truck", "motorcycle", "bicycle"]
    points: list[tuple[float, float]] = Field(min_length=3, max_length=2000)

class Annotation(BaseModel):
    polygons: list[Polygon] = Field(default_factory=list, max_length=200)
    # Coordinates are normalized [0,1]; validation is also applied in the route.

