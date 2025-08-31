from __future__ import annotations
from pathlib import Path
import json, time
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "config" / "wifi_ap_state.json"
STATE.parent.mkdir(parents=True, exist_ok=True)

def write_state(status: str, result: dict | None = None) -> None:
    data = {"status": status, "ts": int(time.time()), "result": result or {}}
    STATE.write_text(json.dumps(data, indent=2))

def read_state() -> dict:
    if not STATE.exists():
        return {"status": "idle", "ts": 0, "result": {}}
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"status": "unknown", "ts": 0, "result": {}}
