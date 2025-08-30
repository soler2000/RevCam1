import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Dict, Any

from aiohttp import web

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

from .config import load_config, save_config, config_to_public_json
from .webrtc_gst import WebRTCBroadcaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "server" / "static"

# Start GLib mainloop for GStreamer (background thread)
Gst.init(None)
_glib_loop = GLib.MainLoop()
threading.Thread(target=_glib_loop.run, daemon=True).start()

# One viewer at a time (good for Zero 2W)
STATE: Dict[str, Any] = {"broadcaster": None}

async def index(_req): return web.FileResponse(STATIC_DIR / "index.html")
async def settings_page(_req): return web.FileResponse(STATIC_DIR / "settings.html")

async def get_config(_req):
  cfg = load_config()
  return web.json_response(config_to_public_json(cfg))

async def post_config(req):
  incoming = await req.json()
  cfg = load_config()

  v = incoming.get("video", {}) or {}
  w = incoming.get("webrtc", {}) or {}
  s = incoming.get("server", {}) or {}

  if v:
    cfg.video.width = int(v.get("width", cfg.video.width))
    cfg.video.height = int(v.get("height", cfg.video.height))
    cfg.video.fps = int(v.get("fps", cfg.video.fps))
    cfg.video.bitrate = int(v.get("bitrate", cfg.video.bitrate))
    if v.get("flip") in ("none","horizontal","vertical"):
      cfg.video.flip = v["flip"]
  if w:
    if isinstance(w.get("stun_servers"), list):
      cfg.webrtc.stun_servers = [str(x) for x in w["stun_servers"]]
    cfg.webrtc.turn = str(w.get("turn", cfg.webrtc.turn))
    cfg.webrtc.turn_username = str(w.get("turn_username", cfg.webrtc.turn_username))
    cfg.webrtc.turn_password = str(w.get("turn_password", cfg.webrtc.turn_password))
  if s:
    cfg.server.host = str(s.get("host", cfg.server.host))
    cfg.server.port = int(s.get("port", cfg.server.port))

  save_config(cfg)
  return web.json_response({"ok": True})

async def ws_handler(req):
  ws = web.WebSocketResponse(autoping=True)
  await ws.prepare(req)

  cfg = load_config()

  # single-viewer: stop previous if any
  if STATE["broadcaster"]:
    try: STATE["broadcaster"].stop()
    except Exception: pass
    STATE["broadcaster"] = None

  loop = asyncio.get_event_loop()
  def send_json(payload):
    asyncio.run_coroutine_threadsafe(ws.send_str(json.dumps(payload)), loop=loop)

  bc = WebRTCBroadcaster(cfg, send_json)
  bc.start()
  STATE["broadcaster"] = bc
  LOG.info("Viewer connected")

  try:
    async for msg in ws:
      if msg.type == web.WSMsgType.TEXT:
        data = json.loads(msg.data)
        if data.get("type") == "offer":
          bc.handle_offer(data["sdp"])
        elif data.get("type") == "ice":
          bc.add_ice(data["candidate"], int(data.get("sdpMLineIndex", 0)))
      elif msg.type == web.WSMsgType.ERROR:
        LOG.warning("WS error: %s", ws.exception())
  finally:
    LOG.info("Viewer disconnected")
    bc.stop()
    if STATE.get("broadcaster") is bc:
      STATE["broadcaster"] = None
    await ws.close()
  return ws

def make_app():
  app = web.Application()
  app.add_routes([
    web.get("/", index),
    web.get("/settings", settings_page),
    web.get("/api/config", get_config),
    web.post("/api/config", post_config),
    web.get("/ws", ws_handler),
    web.static("/static", str(STATIC_DIR)),
  ])
  return app

if __name__ == "__main__":
  cfg = load_config()
  web.run_app(make_app(), host=cfg.server.host, port=cfg.server.port)
