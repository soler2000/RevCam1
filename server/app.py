import asyncio
import json
import logging
import os
from pathlib import Path
from aiohttp import web, WSMsgType

from .config import load_config, save_config, config_to_public_json
from .webrtc_gst import WebRTCBroadcaster
from .wifi import (
    WifiManager,
    nm_scan,
    status as wifi_status,
    start_open_ap,
    stop_ap,
    connect as wifi_connect,
    nm_debug,
)

# Optional state helpers for detached AP start (safe if missing)
try:
    from .wifi_state import write_state, read_state
except Exception:
    def write_state(status, result=None):  # type: ignore
        pass
    def read_state():  # type: ignore
        return {"status": "idle", "ts": 0, "result": {}}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "server" / "static"

# Track active broadcasters for live tweaks
_ACTIVE = set()

# -------------------- Pages --------------------

async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")

async def settings_page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "settings.html")

async def wifi_page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "wifi.html")

# -------------------- Config API --------------------

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
        try:
            cfg.video.rotate = int(v_in["rotate"])
        except Exception:
            cfg.video.rotate = 0
        if cfg.video.rotate not in (0, 90, 180, 270):
            cfg.video.rotate = 0
        changed["rotate"] = cfg.video.rotate

    # Non-live (require reconnect)
    for k in ("width", "height", "fps", "bitrate"):
        if k in v_in:
            setattr(cfg.video, k, int(v_in[k]))
            changed[k] = getattr(cfg.video, k)

    save_config(cfg)

    # Apply live to current broadcasters
    applied = {"mirror": 0, "rotate": 0}
    for bc in list(_ACTIVE):
        try:
            if "mirror" in changed and bc.apply_mirror(cfg.video.mirror):
                applied["mirror"] += 1
            if "rotate" in changed and bc.apply_rotate(cfg.video.rotate):
                applied["rotate"] += 1
        except Exception:
            pass

    return web.json_response(
        {"ok": True, "changed": changed, "live_applied_to": applied, "config": config_to_public_json(cfg)}
    )

# -------------------- WiFi API --------------------

async def api_wifi_status(request: web.Request) -> web.StreamResponse:
    try:
        return web.json_response(wifi_status())
    except Exception as e:
        LOG.exception("wifi_status failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_wifi_scan(request: web.Request) -> web.StreamResponse:
    try:
        nets = await asyncio.to_thread(nm_scan)
        return web.json_response({"ok": True, "networks": nets})
    except Exception as e:
        LOG.exception("wifi_scan failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_wifi_start_ap(request: web.Request) -> web.StreamResponse:
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        ssid = str(body.get("ssid", "RevCam")).strip() or "RevCam"
        res = await asyncio.to_thread(start_open_ap, ssid)
        return web.json_response(res)
    except Exception as e:
        LOG.exception("start_ap failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_wifi_stop_ap(request: web.Request) -> web.StreamResponse:
    try:
        res = await asyncio.to_thread(stop_ap)
        return web.json_response(res)
    except Exception as e:
        LOG.exception("stop_ap failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_wifi_connect(request: web.Request) -> web.StreamResponse:
    try:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        ssid = str(body.get("ssid", "")).strip()
        password = body.get("password")
        if not ssid:
            return web.json_response({"ok": False, "error": "ssid required"}, status=400)
        res = await asyncio.to_thread(wifi_connect, ssid, password if password else None)
        return web.json_response(res)
    except Exception as e:
        LOG.exception("wifi_connect failed")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_wifi_debug(request: web.Request) -> web.StreamResponse:
    try:
        data = await asyncio.to_thread(nm_debug)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

# Detached AP start helpers (so you can reconnect and read the result)
async def api_wifi_ap_state(request: web.Request) -> web.StreamResponse:
    try:
        return web.json_response(read_state())
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)

async def api_wifi_start_ap_detached(request: web.Request) -> web.StreamResponse:
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        ssid = str(body.get("ssid", "RevCam")).strip() or "RevCam"
        write_state("starting", {"ssid": ssid})
        loop = asyncio.get_running_loop()
        async def worker():
            try:
                res = await asyncio.to_thread(start_open_ap, ssid)
                write_state("ok", res)
            except Exception as e:
                write_state("error", {"message": str(e)})
        loop.create_task(worker())
        return web.json_response({"ok": True, "detached": True, "ssid": ssid})
    except Exception as e:
        write_state("error", {"message": str(e)})
        return web.json_response({"ok": False, "error": str(e)}, status=500)

# -------------------- WebSocket / WebRTC --------------------

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
        bc.start()  # server is offerer
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

# -------------------- App factory & startup --------------------

wifi_mgr = WifiManager()

async def on_startup(app: web.Application):
    # Auto-hotspot is DISABLED by default. Set REVCAM_AUTOHOTSPOT=1 to enable.
    enabled = str(os.environ.get('REVCAM_AUTOHOTSPOT', '0')).lower() in ('1','true','yes','on')
    if enabled:
        try:
            delay = int(os.environ.get('REVCAM_AUTOHOTSPOT_DELAY', '30'))
        except Exception:
            delay = 30
        app['wifi_task'] = asyncio.create_task(wifi_mgr.watchdog_startup(delay))
        LOG.info('Auto-hotspot enabled (delay=%ss)', delay)
    else:
        LOG.info('Auto-hotspot is disabled (REVCAM_AUTOHOTSPOT=0)')

async def on_cleanup(app: web.Application):
    task = app.get("wifi_task")
    if task:
        task.cancel()

def make_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # Pages
    app.router.add_get("/", index)
    app.router.add_get("/settings", settings_page)
    app.router.add_get("/wifi", wifi_page)

    # Config API
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", post_config)

    # WiFi API
    app.router.add_get("/api/wifi/status", api_wifi_status)
    app.router.add_get("/api/wifi/scan", api_wifi_scan)
    app.router.add_post("/api/wifi/start_ap", api_wifi_start_ap)
    app.router.add_post("/api/wifi/stop_ap", api_wifi_stop_ap)
    app.router.add_post("/api/wifi/connect", api_wifi_connect)
    app.router.add_get("/api/wifi/debug", api_wifi_debug)
    app.router.add_get("/api/wifi/ap_state", api_wifi_ap_state)
    app.router.add_post("/api/wifi/start_ap_detached", api_wifi_start_ap_detached)

    # Static & WebSocket
    app.router.add_static("/static/", path=str(STATIC_DIR), show_index=False)
    app.router.add_get("/ws", ws_handler)
    return app

if __name__ == "__main__":
    cfg = load_config()
    web.run_app(make_app(), host=cfg.server.host, port=cfg.server.port)
