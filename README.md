RevCam1 — Raspberry Pi Zero 2W WebRTC Camera (H.264 HW encode)

Low-CPU, low-latency live camera streaming to iPhone/iPad using WebRTC (H.264) on Raspberry Pi OS Bookworm.

Pipeline:
  libcamerasrc -> videoflip -> (overlay hook) -> v4l2h264enc -> h264parse -> rtph264pay -> webrtcbin

Run (dev):
  source .venv/bin/activate
  python -m server.app
  Then open: http://<pi-ip>:8080/

Settings page lets you flip: none | horizontal | vertical
