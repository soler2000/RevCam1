# RevCam1

Low-latency WebRTC camera streamer for Raspberry Pi Zero 2 W (Bookworm).  
Optimized for low CPU and fast live view on iPhone/iPad (Safari) and desktop browsers.

- Default codec: VP8 (works reliably across Safari/Chrome/Firefox)
- Live controls: mirror (none | horizontal | vertical) + rotate (0 | 90 | 180 | 270) — applied instantly, no reconnect
- Web UI: Viewer + Settings
- Future-proof pipeline: overlay hook placed server-side before the encoder
- Simple run: python -m server.app

---

## Demo (what you’ll see)

- Viewer (path “/”): video element and a small status window (below the player).
- Settings (path “/settings”): change resolution/fps/bitrate and mirror + rotate on the fly.

---

## Architecture

Server (Python / aiohttp)  
Serves static UI, REST API, and a WebSocket for WebRTC signaling. The server acts as the SDP offerer to minimize browser/PT mismatches.

GStreamer pipeline

    libcamerasrc → v4l2convert/videoconvert → videoflip(mirror) → videoflip(rotate)
    → tee → queue → [overlay hook] → queue → vp8enc → rtpvp8pay → webrtcbin

Client (Browser)  
Standard WebRTC peer, answers the server’s offer. Auto-plays inline (muted), with a manual ▶︎ button if the browser blocks autoplay.

---

## Why VP8 by default?

- Zero 2 W can software-encode H.264 with x264enc, but Safari’s H.264 profile/level quirks can cause “connected but black video.”
- VP8 is widely interoperable and performs well at 480p–540p on the Zero 2 W, providing a smooth baseline.
- H.264 is still possible (see Optional: H.264).

---

## Requirements

- Raspberry Pi Zero 2 W  
- Raspberry Pi OS Bookworm  
- Camera connected & enabled (libcamera)

Install packages:

    sudo apt-get update
    sudo apt-get -y install \
      rpicam-apps \
      gstreamer1.0-libcamera \
      gstreamer1.0-tools gstreamer1.0-plugins-base \
      gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
      v4l-utils python3-venv python3-gi python3-gi-cairo \
      gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0

Grant video access:

    sudo usermod -aG video $USER
    # log out/in (or new SSH session) so the group applies

---

## Install & Run

Clone and enter:

    git clone https://github.com/soler2000/RevCam1.git
    cd RevCam1

Python venv (use system-site-packages so GI/GStreamer typelibs are visible):

    python3 -m venv --system-site-packages .venv
    source .venv/bin/activate

Python deps:

    pip install -r requirements.txt

Run:

    python -m server.app

Open the viewer:

    http://<pi-ip>:8080/

---

## Web UI

Viewer: GET /

- Live stream + status (under the player).  
- Mobile: tap ▶︎ if autoplay is blocked.

Settings: GET /settings

- Resolution: width × height
- Frame rate: fps
- Bitrate: bitrate (bps)
- Mirror: none | horizontal | vertical (applies live)
- Rotate: 0 | 90 | 180 | 270 (applies live)

---

## REST API

GET /api/config → current configuration (safe for UI)

POST /api/config → update config (any subset of fields). Example body:

    {
      "video": {
        "width": 960,
        "height": 540,
        "fps": 25,
        "bitrate": 1200000,
        "mirror": "horizontal",
        "rotate": 180
      }
    }

Example response:

    {
      "ok": true,
      "changed": { ... },
      "live_applied_to": { "mirror": 1, "rotate": 1 },
      "config": { ... }
    }

Notes

- mirror & rotate apply immediately to active viewers.
- Resolution/fps/bitrate take effect on next reconnect.

---

## Systemd service (auto-start)

    # Edit systemd/revcam.service: set User= and ExecStart= to your paths
    sudo cp systemd/revcam.service /etc/systemd/system/revcam.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now revcam
    sudo systemctl status revcam --no-pager

---

## Optional: enable H.264 (advanced)

If you need H.264 (e.g., for certain clients or overlays), switch the encoder to software x264.

Ensure packages:

    sudo apt-get -y install gstreamer1.0-plugins-ugly gstreamer1.0-libav
    gst-inspect-1.0 x264enc | head -n1

Replace the VP8 chain with:

    x264enc → h264parse → rtph264pay

Advertise RTP caps:

    application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000,packetization-mode=1

Safari tips

- Prefer Baseline profile, level 3.1 and frequent keyframes (e.g., every 1–2 seconds).  
- If you see “connected, black video”, it’s usually a profile/level mismatch or SPS/PPS cadence issue.

VP8 remains the recommended default on Zero 2 W for simplicity and compatibility.

---

## Performance tips (Zero 2 W)

- Start with 960×540 @ 25fps, bitrate 1.0–1.5 Mbps.
- If CPU is tight, try 854×480 @ 25fps, bitrate 0.8–1.2 Mbps.
- Keep overlay simple (text/time/watermark). Heavy overlays increase CPU.
- One viewer at a time is ideal; for many viewers, consider a WebRTC SFU/gateway (Janus/Pion) later.

---

## Files & layout

    RevCam1/
    ├─ server/
    │  ├─ app.py           # aiohttp app, REST, WS signaling (server offers)
    │  ├─ webrtc_gst.py    # GStreamer pipeline + WebRTC
    │  ├─ overlay.py       # overlay hook (identity by default)
    │  ├─ config.py        # dataclasses + YAML load/save
    │  └─ static/
    │     ├─ index.html    # viewer UI (status under video)
    │     ├─ settings.html # settings UI (mirror + rotate)
    │     └─ app.js        # WebRTC client logic
    ├─ config/
    │  └─ config.yaml      # generated at first run (gitignored)
    ├─ systemd/
    │  └─ revcam.service   # service unit file
    ├─ requirements.txt
    └─ README.md

---

## Troubleshooting

Web page loads but no video

- Ensure packages installed (see Requirements).
- Browser status should show: answer sent, ice: connected, conn: connected, ontrack → video should play. Tap ▶︎ if blocked.
- Server log: look for “Linked RTP -> …: OK”. If missing, your webrtcbin uses different pad names; this code supports both send_rtp_sink_%u and sink_%u.

Camera errors

- rpicam-hello -n -t 1000 should show no errors.
- gst-launch-1.0 -v libcamerasrc ! fakesink -e should run without ERROR lines.

GitHub push: Permission denied (publickey)

- Add your SSH key to GitHub or push via HTTPS with a Personal Access Token.

---

## Roadmap

- Optional H.264 profile manager (Baseline/High + level)
- Simple on-frame overlay (watermark/time)
- Multi-viewer support via a gateway (Janus/Pion)
- Auth for /settings and /api/config (when exposed beyond LAN)

---

## License

MIT (or choose your license of preference).

---

## WiFi (fallback hotspot + scan/connect)

- On startup, if no WiFi connection is detected within **30 seconds**, RevCam1 starts an **open hotspot** named **RevCam** (no password).
- Manage WiFi at **/wifi**:
  - **Start/Stop hotspot**
  - **Scan** nearby networks
  - **Connect** to a selected SSID (password prompt for secured APs)
