import logging
from typing import Callable, Optional, Dict, Any

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GstWebRTC, GstSdp

from .overlay import make_overlay_element
from .config import Config

LOG = logging.getLogger("webrtc")

def _flip_to_method(flip: str) -> str:
    return {
        "none": "none",
        "horizontal": "horizontal-flip",
        "vertical": "vertical-flip",
    }.get(flip, "none")

class WebRTCBroadcaster:
    """One pipeline per viewer (simple + Pi Zero 2W friendly)."""
    def __init__(self, cfg: Config, send_json: Callable[[Dict[str, Any]], None]):
        self.cfg = cfg
        self._send_json = send_json
        self.pipeline: Optional[Gst.Pipeline] = None
        self.webrtc: Optional[Gst.Element] = None

    def build_pipeline(self) -> None:
        assert self.pipeline is None
        v = self.cfg.video

        p = Gst.Pipeline.new("rev-pipe")

        src = Gst.ElementFactory.make("libcamerasrc", "src")
        if not src: raise RuntimeError("libcamerasrc missing (install libcamera)")

        capsf = Gst.ElementFactory.make("capsfilter", "caps")
        caps = Gst.Caps.from_string(f"video/x-raw,width={v.width},height={v.height},framerate={v.fps}/1")
        capsf.set_property("caps", caps)

        vconv = Gst.ElementFactory.make("videoconvert", "vconv")
        vflip = Gst.ElementFactory.make("videoflip", "vflip")
        vflip.set_property("method", _flip_to_method(v.flip))

        tee = Gst.ElementFactory.make("tee", "tee")
        q1 = Gst.ElementFactory.make("queue", "q1")
        overlay = make_overlay_element()
        q2 = Gst.ElementFactory.make("queue", "q2")

        enc = Gst.ElementFactory.make("v4l2h264enc", "enc")
        if not enc: raise RuntimeError("v4l2h264enc missing (plugins?)")
        try: enc.set_property("bitrate", int(v.bitrate))
        except Exception: LOG.warning("v4l2h264enc: could not set bitrate")

        parse = Gst.ElementFactory.make("h264parse", "parse")
        parse.set_property("config-interval", -1)
        pay = Gst.ElementFactory.make("rtph264pay", "pay")
        pay.set_property("pt", 96)
        pay.set_property("config-interval", -1)

        webrtc = Gst.ElementFactory.make("webrtcbin", "webrtc")
        if not webrtc: raise RuntimeError("webrtcbin missing (gstreamer1.0-plugins-bad)")
        self.webrtc = webrtc

        # STUN/TURN (first STUN server only; fine for LAN)
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

        for e in [src, capsf, vconv, vflip, tee, q1, overlay, q2, enc, parse, pay, webrtc]:
            p.add(e)

        if not Gst.Element.link_many(src, capsf, vconv, vflip, tee):
            raise RuntimeError("link src->tee failed")

        tee_pad = tee.get_request_pad("src_%u")
        if tee_pad is None: raise RuntimeError("tee request pad failed")
        if q1.get_static_pad("sink").link(tee_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("link tee->q1 failed")

        if not Gst.Element.link_many(q1, overlay, q2, enc, parse, pay):
            raise RuntimeError("link branch failed")

        sink = webrtc.get_request_pad("sink_%u")
        if sink is None: raise RuntimeError("webrtcbin sink request failed")
        if pay.get_static_pad("src").link(sink) != Gst.PadLinkReturn.OK:
            raise RuntimeError("link pay->webrtcbin failed")

        # callbacks + bus
        webrtc.connect("on-ice-candidate", self._on_ice_candidate)
        bus = p.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus)

        self.pipeline = p

    def start(self) -> None:
        if self.pipeline is None: self.build_pipeline()
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("pipeline PLAYING failed")

    def stop(self) -> None:
        if self.pipeline: self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.webrtc = None

    def handle_offer(self, sdp_text: str) -> None:
        assert self.webrtc is not None
        ok, sdp = GstSdp.SDPMessage.new()
        if ok != GstSdp.SDPResult.OK: raise RuntimeError("SDPMessage.new failed")
        if GstSdp.sdp_message_parse_buffer(sdp_text.encode(), sdp) != GstSdp.SDPResult.OK:
            raise RuntimeError("SDP parse failed")
        offer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdp)

        def on_set_remote(_promise, _):
            self.webrtc.emit("create-answer", None, Gst.Promise.new_with_change_func(on_answer_created, None))

        def on_answer_created(promise, _):
            reply = promise.get_reply()
            answer = reply.get_value("answer")
            self.webrtc.emit("set-local-description", answer, Gst.Promise.new())
            self._send_json({"type": "answer", "sdp": answer.sdp.as_text()})

        self.webrtc.emit("set-remote-description", offer, Gst.Promise.new_with_change_func(on_set_remote, None))

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
