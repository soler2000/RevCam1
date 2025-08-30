(async function(){
  const statusEl = document.getElementById('status');
  const btn = document.getElementById('connectBtn');
  const video = document.getElementById('video');
  let pc, ws;

  function setStatus(s){ statusEl.textContent = s; }

  async function fetchConfig(){
    const r = await fetch('/api/config');
    return r.json();
  }

  async function connect(){
    if (pc) return;
    const cfg = await fetchConfig();

    const iceServers = [];
    if (cfg.webrtc?.stun_servers?.length) iceServers.push(...cfg.webrtc.stun_servers.map(s=>({urls:s})));
    if (cfg.webrtc?.turn){
      const t = cfg.webrtc;
      const entry = {urls: t.turn};
      if (t.turn_username && t.turn_password){ entry.username=t.turn_username; entry.credential=t.turn_password; }
      iceServers.push(entry);
    }

    pc = new RTCPeerConnection({iceServers});
    pc.addTransceiver('video', {direction:'recvonly'});
    pc.oniceconnectionstatechange = () => setStatus(`pc: ${pc.iceConnectionState}`);
    pc.ontrack = (ev) => { video.srcObject = ev.streams[0]; };

    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    ws.onopen = async () => {
      setStatus('signaling open');
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      ws.send(JSON.stringify({type:'offer', sdp: offer.sdp}));
    };
    ws.onmessage = async (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === 'answer'){
        await pc.setRemoteDescription({type:'answer', sdp:data.sdp});
        setStatus('connected');
      } else if (data.type === 'ice'){
        try { await pc.addIceCandidate({candidate:data.candidate, sdpMLineIndex:data.sdpMLineIndex}); } catch {}
      }
    };
    ws.onerror = () => setStatus('ws error');
    ws.onclose = () => setStatus('ws closed');

    pc.onicecandidate = ({candidate}) => {
      if (candidate) ws.send(JSON.stringify({type:'ice', candidate:candidate.candidate, sdpMLineIndex:candidate.sdpMLineIndex || 0}));
    };
  }

  btn.addEventListener('click', connect);
  connect().catch(e=>setStatus('error: '+e.message));
})();
