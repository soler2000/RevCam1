from dataclasses import dataclass, asdict
from pathlib import Path
import yaml
from typing import List, Dict, Any

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

@dataclass
class VideoConfig:
    width: int = 1280
    height: int = 720
    fps: int = 30
    bitrate: int = 2_500_000
    flip: str = "none"  # none|horizontal|vertical

@dataclass
class WebRTCConfig:
    stun_servers: List[str] = None
    turn: str = ""
    turn_username: str = ""
    turn_password: str = ""
    def __post_init__(self):
        if self.stun_servers is None:
            self.stun_servers = ["stun:stun.l.google.com:19302"]

@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080

@dataclass
class Config:
    video: VideoConfig = VideoConfig()
    webrtc: WebRTCConfig = WebRTCConfig()
    server: ServerConfig = ServerConfig()

def _dict_to_config(d: Dict[str, Any]) -> Config:
    v = d.get("video", {}) or {}
    w = d.get("webrtc", {}) or {}
    s = d.get("server", {}) or {}
    return Config(
        video=VideoConfig(**{**asdict(VideoConfig()), **v}),
        webrtc=WebRTCConfig(**{**asdict(WebRTCConfig()), **w}),
        server=ServerConfig(**{**asdict(ServerConfig()), **s}),
    )

def load_config() -> Config:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    return _dict_to_config(data)

def save_config(cfg: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump({
            "video": asdict(cfg.video),
            "webrtc": asdict(cfg.webrtc),
            "server": asdict(cfg.server),
        }, f)

def config_to_public_json(cfg: Config) -> Dict[str, Any]:
    return {
        "video": asdict(cfg.video),
        "webrtc": {
            "stun_servers": cfg.webrtc.stun_servers,
            "turn": cfg.webrtc.turn,
            "turn_username": cfg.webrtc.turn_username,
            "turn_password": cfg.webrtc.turn_password,
        },
        "server": asdict(cfg.server),
    }
