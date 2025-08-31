from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG_DIR = ROOT / "config"
CFG_PATH = CFG_DIR / "config.yaml"

@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080

@dataclass
class WebRTCConfig:
    stun_servers: List[str] = field(default_factory=lambda: ["stun:stun.l.google.com:19302"])
    turn: Optional[str] = None
    turn_username: Optional[str] = None
    turn_password: Optional[str] = None

@dataclass
class VideoConfig:
    width: int = 960
    height: int = 540
    fps: int = 25
    bitrate: int = 1_200_000
    # New split fields
    mirror: str = "none"          # one of: none|horizontal|vertical
    rotate: int = 0               # one of: 0|90|180|270
    # Back-compat: old single "flip" field (ignored if mirror/rotate are present)
    flip: str = "none"

@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    webrtc: WebRTCConfig = field(default_factory=WebRTCConfig)
    video: VideoConfig = field(default_factory=VideoConfig)

def _coerce_video(d: Dict[str, Any]) -> VideoConfig:
    v = VideoConfig()
    v.width   = int(d.get("width", v.width))
    v.height  = int(d.get("height", v.height))
    v.fps     = int(d.get("fps", v.fps))
    v.bitrate = int(d.get("bitrate", v.bitrate))
    # Prefer new fields
    mirror = str(d.get("mirror", v.mirror)).lower()
    rotate = d.get("rotate", v.rotate)
    # Back-compat: parse old "flip" if new fields missing
    if "mirror" not in d and "rotate" not in d:
        old = str(d.get("flip", "none")).lower()
        if old in ("horizontal","vertical"):
            mirror = old
        elif old in ("rotate-90","rotate90","90"):
            rotate = 90
        elif old in ("rotate-180","rotate180","180"):
            rotate = 180
        elif old in ("rotate-270","rotate270","270"):
            rotate = 270
    v.mirror = mirror if mirror in ("none","horizontal","vertical") else "none"
    try:
        v.rotate = int(rotate)
    except Exception:
        v.rotate = 0
    if v.rotate not in (0,90,180,270):
        v.rotate = 0
    # keep old field around when saving for clarity
    v.flip = d.get("flip", "none")
    return v

def load_config() -> Config:
    if not CFG_PATH.exists():
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = Config()
        save_config(cfg)
        return cfg
    data = yaml.safe_load(CFG_PATH.read_text()) or {}
    cfg = Config()
    s = data.get("server", {})
    w = data.get("webrtc", {})
    v = data.get("video", {})
    cfg.server.host = str(s.get("host", cfg.server.host))
    cfg.server.port = int(s.get("port", cfg.server.port))
    cfg.webrtc.stun_servers = list(w.get("stun_servers", cfg.webrtc.stun_servers))
    cfg.webrtc.turn = w.get("turn", cfg.webrtc.turn)
    cfg.webrtc.turn_username = w.get("turn_username", cfg.webrtc.turn_username)
    cfg.webrtc.turn_password = w.get("turn_password", cfg.webrtc.turn_password)
    cfg.video = _coerce_video(v)
    return cfg

def save_config(cfg: Config) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "webrtc": {
            "stun_servers": cfg.webrtc.stun_servers,
            "turn": cfg.webrtc.turn,
            "turn_username": cfg.webrtc.turn_username,
            "turn_password": cfg.webrtc.turn_password,
        },
        "video": {
            "width": cfg.video.width,
            "height": cfg.video.height,
            "fps": cfg.video.fps,
            "bitrate": cfg.video.bitrate,
            "mirror": cfg.video.mirror,
            "rotate": cfg.video.rotate,
            "flip": cfg.video.flip,  # keep for back-compat
        },
    }
    CFG_PATH.write_text(yaml.safe_dump(data, sort_keys=False))

def config_to_public_json(cfg: Config) -> Dict[str, Any]:
    return {
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "webrtc": {
            "stun_servers": cfg.webrtc.stun_servers,
            "turn": cfg.webrtc.turn,
            "turn_username": cfg.webrtc.turn_username,
            "turn_password": cfg.webrtc.turn_password,
        },
        "video": {
            "width": cfg.video.width,
            "height": cfg.video.height,
            "fps": cfg.video.fps,
            "bitrate": cfg.video.bitrate,
            "mirror": cfg.video.mirror,
            "rotate": cfg.video.rotate,
        },
    }
