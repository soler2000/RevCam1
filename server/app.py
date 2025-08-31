import asyncio
import json
import logging
from pathlib import Path
from aiohttp import web, WSMsgType

from .config import load_config, save_config, config_to_public_json
from .webrtc_gst import WebRTCBroadcaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "server" / "static"

# Track active broadcasters for live tweaks
_ACTIVE = set()

async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")

async def settings_page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "settings.html")

async def get_config(request: web.Request) -> web.StreamResponse:
    return web.json_response(config_to_public_json(load_config()))

async def post_config(request: web.Request) -> web.StreamResponse:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    cfg = load_config()
    v_in = body.get("video") or {}
    changed = {}

    # Live-applicable
    if "mirror" in v_in:
        cfg.video.mirror = str(v_in["mirror"])
        changed["mirror"] = cfg.video.mirror
    if "rotate" in v_in:
        try: cfg.video.rotate = int(v_in["rotate"])
        except Exception: cfg.video.rotate = 0
        if cfg.video.rotate not in (0,90,180,270): cfg.video.rotate = 0
        changed["rotate"] = cfg.video.rotate

    # Non-live (require reconnect)
    for k in ("width","height","fps","bitrate"):
        if k in v_in:
            setattr(cfg.video, k, int(v_in[k]))
            changed[k] = getattr(cfg.video, k)

    save_config(cfg)

    # Apply live: mirror & rotate
    applied = {"mirror": 0, "rotate": 0}
    for bc in list(_ACTIVE):
        try:
            if "mirror" in changed and bc.apply_mirror(cfg.video.mirror): applied["mirror"] += 1
            if "rotate" in changed and bc.apply_rotate(cfg.video.rotate): applied["rotate"] += 1
        except Exception:
            pass

    return web.json_response({"ok": True, "changed": changed, "live_applied_to": applied, "config": config_to_public_json(cfg)})

async def ws_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    cfg = load_config()
    loop = asyncio.get_running_loop()

    def send_json(payload):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_str(json.dumps(payload)), loop)
        except Exception as e:
            LOG.warning("send_json scheduling failed: %s", e)

    bc = WebRTCBroadcaster(cfg, send_json)
    _ACTIVE.add(bc)
    try:
        LOG.info("Viewer connected")
        bc.start()  # server offers SDP
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                t = data.get("type")
                if t == "answer":
                    bc.handle_answer(data.get("sdp", ""))
                elif t == "ice":
                    bc.add_ice(data.get("candidate", ""), int(data.get("sdpMLineIndex", 0)))
            elif msg.type == WSMsgType.ERROR:
                LOG.error("WS error: %s", ws.exception())
    finally:
        LOG.info("Viewer disconnected")
        try:
            if hasattr(bc, "stop"):
                bc.stop()
        except Exception as e:
            LOG.warning("bc.stop failed: %s", e)
        _ACTIVE.discard(bc)
        await ws.close()
    return ws

def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/settings", settings_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", post_config)
    app.router.add_static("/static/", path=str(STATIC_DIR), show_index=False)
    app.router.add_get("/ws", ws_handler)
    return app

if __name__ == "__main__":
    cfg = load_config()
    web.run_app(make_app(), host=cfg.server.host, port=cfg.server.port)
