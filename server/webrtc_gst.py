import logging
from typing import Callable, Optional, Dict, Any

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GstWebRTC, GstSdp

from .overlay import make_overlay_element
from .config import Config

Gst.init(None)
LOG = logging.getLogger("webrtc")

def _mirror_to_method(mirror: str) -> str:
    m = (mirror or "none").lower()
    return {"none":"none","horizontal":"horizontal-flip","vertical":"vertical-flip"}.get(m, "none")

def _rotate_to_method(r: int) -> str:
    try: r = int(r)
    except Exception: r = 0
    return {0:"none", 90:"rotate-90", 180:"rotate-180", 270:"rotate-270"}.get(r, "none")

def _link(a, b, label=""):
    if not a.link(b):
        raise RuntimeError(f"Failed to link {a.name} -> {b.name} ({label})")

class WebRTCBroadcaster:
    """Zero 2W friendly — SOFTWARE VP8; server is SDP offerer. Supports independent mirror+rotate with live updates."""
    def __init__(self, cfg: Config, send_json: Callable[[Dict[str, Any]], None]):
        self.cfg = cfg
        self._send_json = send_json
        self.pipeline: Optional[Gst.Pipeline] = None
        self.webrtc: Optional[Gst.Element] = None
        self._rtp_src_pad: Optional[Gst.Pad] = None
        self.vflip_mirror: Optional[Gst.Element] = None
        self.vflip_rotate: Optional[Gst.Element] = None

    def _on_webrtc_pad_added(self, _webrtc: Gst.Element, pad: Gst.Pad):
        name = pad.get_name()
        LOG.info("webrtcbin pad-added: %s (dir=%s)", name, pad.get_direction().value_nick)
        if (name.startswith("send_rtp_sink_") or name.startswith("sink_")) and pad.get_direction() == Gst.PadDirection.SINK and self._rtp_src_pad:
            if not pad.is_linked():
                res = self._rtp_src_pad.link(pad)
                LOG.info("Linked RTP -> %s: %s", name, res)

    def _request_any_send_sink(self, webrtc: Gst.Element) -> Optional[Gst.Pad]:
        pad = webrtc.get_request_pad("send_rtp_sink_%u")
        if pad: return pad
        pad = webrtc.get_request_pad("sink_%u")
        if pad: return pad
        for nm in ("send_rtp_sink_0", "sink_0"):
            p = webrtc.get_static_pad(nm)
            if p and (not p.is_linked()):
                return p
        try:
            for tmpl in webrtc.get_pad_template_list() or []:
                if tmpl.direction == Gst.PadDirection.SINK and ("send_rtp_sink" in tmpl.name_template or tmpl.name_template.startswith("sink_")):
                    p = webrtc.get_request_pad(tmpl.name_template)
                    if p: return p
        except Exception:
            pass
        return None

    def _make_vp8_chain(self, p: Gst.Pipeline):
        v = self.cfg.video
        enc = Gst.ElementFactory.make("vp8enc", "vp8enc")
        if not enc:
            raise RuntimeError("vp8enc not available (apt install gstreamer1.0-plugins-good)")
        for k, val in {
            "deadline": 1, "cpu-used": 8, "end-usage": 1,
            "target-bitrate": int(v.bitrate), "error-resilient": 1,
            "keyframe-max-dist": max(1, int(v.fps * 2)), "threads": 2
        }.items():
            try: enc.set_property(k, val)
            except Exception: pass
        pay = Gst.ElementFactory.make("rtpvp8pay", "pay"); pay.set_property("pt", 96)
        rtpcapsf = Gst.ElementFactory.make("capsfilter", "rtpcaps")
        rtpcapsf.set_property("caps", Gst.Caps.from_string(
            "application/x-rtp,media=video,encoding-name=VP8,payload=96,clock-rate=90000"
        ))
        for e in [enc, pay, rtpcapsf]: p.add(e)
        return enc, pay, rtpcapsf

    def build_pipeline(self) -> None:
        assert self.pipeline is None
        v = self.cfg.video
        p = Gst.Pipeline.new("rev-pipe")

        src = Gst.ElementFactory.make("libcamerasrc", "src")
        if not src:
            raise RuntimeError("libcamerasrc missing (apt install gstreamer1.0-libcamera rpicam-apps)")

        capsf = Gst.ElementFactory.make("capsfilter", "caps")
        capsf.set_property("caps", Gst.Caps.from_string(
            f"video/x-raw,format=I420,width={v.width},height={v.height},framerate={v.fps}/1"
        ))

        vconv = Gst.ElementFactory.make("v4l2convert", "vconv") or Gst.ElementFactory.make("videoconvert", "vconv")
        self.vflip_mirror = Gst.ElementFactory.make("videoflip", "vflip_mirror")
        self.vflip_mirror.set_property("method", _mirror_to_method(v.mirror))

        self.vflip_rotate = Gst.ElementFactory.make("videoflip", "vflip_rotate")
        self.vflip_rotate.set_property("method", _rotate_to_method(v.rotate))

        tee = Gst.ElementFactory.make("tee", "tee")
        q1 = Gst.ElementFactory.make("queue", "q1"); q1.set_property("leaky", 2); q1.set_property("max-size-buffers", 2)
        qenc = Gst.ElementFactory.make("queue", "qenc"); qenc.set_property("leaky", 2); qenc.set_property("max-size-buffers", 2)
        overlay = make_overlay_element()
        q2 = Gst.ElementFactory.make("queue", "q2")

        enc, pay, rtpcapsf = self._make_vp8_chain(p)

        webrtc = Gst.ElementFactory.make("webrtcbin", "webrtc")
        if not webrtc:
            raise RuntimeError("webrtcbin missing (apt install gstreamer1.0-plugins-bad)")
        self.webrtc = webrtc

        # STUN/TURN
        w = self.cfg.webrtc
        if w.stun_servers:
            webrtc.set_property("stun-server", f"stun://{w.stun_servers[0].split('stun:')[-1]}")
        if w.turn:
            uri = w.turn
            if uri.startswith("turn:"): uri = "turn://" + uri.split("turn:")[1]
            if w.turn_username and w.turn_password:
                proto, rest = uri.split("://", 1)
                uri = f"{proto}://{w.turn_username}:{w.turn_password}@{rest}"
            webrtc.set_property("turn-server", uri)

        # Add everything
        for e in [src, capsf, vconv, self.vflip_mirror, self.vflip_rotate, tee, q1, overlay, q2, qenc, enc, pay, rtpcapsf, webrtc]:
            p.add(e)

        # Camera chain
        _link(src, capsf, "src->caps")
        _link(capsf, vconv, "caps->vconv")
        _link(vconv, self.vflip_mirror, "vconv->mirror")
        _link(self.vflip_mirror, self.vflip_rotate, "mirror->rotate")
        _link(self.vflip_rotate, tee, "rotate->tee")

        tee_src = tee.get_request_pad("src_%u")
        if tee_src is None: raise RuntimeError("tee request pad failed")
        q1_sink = q1.get_static_pad("sink")
        if q1_sink is None: raise RuntimeError("q1 sink pad missing")
        if tee_src.link(q1_sink) != Gst.PadLinkReturn.OK:
            raise RuntimeError("link tee.src -> q1.sink failed")

        _link(q1, overlay, "q1->overlay")
        _link(overlay, q2, "overlay->q2")
        _link(q2, qenc, "q2->qenc")
        _link(qenc, enc, "qenc->enc")
        _link(enc, pay, "enc->pay")
        _link(pay, rtpcapsf, "pay->rtpcaps")

        self._rtp_src_pad = rtpcapsf.get_static_pad("src")
        webrtc.connect("pad-added", self._on_webrtc_pad_added)

        # Bus + ICE
        webrtc.connect("on-ice-candidate", self._on_ice_candidate)
        bus = p.get_bus(); bus.add_signal_watch(); bus.connect("message", self._on_bus)

        self.pipeline = p

    def start(self) -> None:
        if self.pipeline is None:
            self.build_pipeline()
        # Ensure sender pad exists
        try:
            vp8_caps = Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=VP8,clock-rate=90000,payload=96")
            self.webrtc.emit("add-transceiver", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, vp8_caps)
            LOG.info("webrtcbin transceiver added (SENDONLY VP8)")
        except Exception as e:
            LOG.info("add-transceiver not available/needed: %s", e)

        pad = self._request_any_send_sink(self.webrtc)
        if pad and self._rtp_src_pad:
            res = self._rtp_src_pad.link(pad)
            LOG.info("Linked RTP -> %s: %s", pad.get_name(), res)
        else:
            LOG.info("No send sink pad available yet; waiting for pad-added…")

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("pipeline PLAYING failed (vp8)")

        # Offer
        def on_offer_created(promise, _):
            reply = promise.get_reply()
            offer = reply.get_value("offer")
            self.webrtc.emit("set-local-description", offer, Gst.Promise.new())
            self._send_json({"type": "offer", "sdp": offer.sdp.as_text()})
            LOG.info("Sent SDP offer")
        self.webrtc.emit("create-offer", None, Gst.Promise.new_with_change_func(on_offer_created, None))

    def handle_answer(self, sdp_text: str) -> None:
        assert self.webrtc is not None
        ok, sdp = GstSdp.SDPMessage.new()
        if ok != GstSdp.SDPResult.OK: raise RuntimeError("SDPMessage.new failed")
        if GstSdp.sdp_message_parse_buffer(sdp_text.encode(), sdp) != GstSdp.SDPResult.OK:
            raise RuntimeError("SDP parse failed")
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
        self.webrtc.emit("set-remote-description", answer, Gst.Promise.new())
        LOG.info("Set remote ANSWER")

    def add_ice(self, candidate: str, sdp_mline_index: int) -> None:
        if self.webrtc:
            self.webrtc.emit("add-ice-candidate", int(sdp_mline_index), candidate)

    def _on_ice_candidate(self, _webrtc, mlineindex, candidate):
        self._send_json({"type": "ice", "candidate": candidate, "sdpMLineIndex": int(mlineindex)})

    def _on_bus(self, _bus, msg):
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            LOG.error("GStreamer ERROR: %s (%s)", err, dbg)
        elif t == Gst.MessageType.WARNING:
            err, dbg = msg.parse_warning()
            LOG.warning("GStreamer WARN: %s (%s)", err, dbg)
        elif t == Gst.MessageType.EOS:
            LOG.info("GStreamer EOS")

    def stop(self) -> None:
        try:
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
        finally:
            self.pipeline = None
            self.webrtc = None
            self._rtp_src_pad = None

    # ---- live controls ----
    def apply_mirror(self, mirror: str) -> bool:
        self.cfg.video.mirror = mirror
        if self.vflip_mirror:
            try:
                self.vflip_mirror.set_property("method", _mirror_to_method(mirror))
                LOG.info("Applied live mirror: %s", mirror)
                return True
            except Exception as e:
                LOG.warning("Failed apply mirror: %s", e)
        return False

    def apply_rotate(self, rotate: int) -> bool:
        self.cfg.video.rotate = int(rotate) if str(rotate).isdigit() else 0
        if self.vflip_rotate:
            try:
                self.vflip_rotate.set_property("method", _rotate_to_method(self.cfg.video.rotate))
                LOG.info("Applied live rotate: %s", self.cfg.video.rotate)
                return True
            except Exception as e:
                LOG.warning("Failed apply rotate: %s", e)
        return False
