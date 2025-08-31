(() => {
  const statusEl = document.getElementById('status');
  const video = document.getElementById('v');
  const playBtn = document.getElementById('play');
  const log = (...a) => {
    const line = a.map(x => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ');
    console.log('[viewer]', ...a);
    statusEl.textContent = (statusEl.textContent + '\n' + line).trim().slice(-3000);
  };

  video.muted = true; video.playsInline = true; video.autoplay = true; video.controls = true;
  ['loadedmetadata','loadeddata','canplay','play','playing','pause','waiting','stalled','emptied','error','suspend','timeupdate'].forEach(ev => {
    video.addEventListener(ev, () => log('video event:', ev, 't=', video.currentTime.toFixed(2)));
  });
  playBtn.onclick = async () => { try { await video.play(); log('manual play() OK'); } catch (e) { log('manual play() failed:', e?.message || e); } };

  (async () => {
    const cfg = await fetch('/api/config').then(r => r.json()).catch(() => ({}));
    const iceServers = [];
    if (cfg.webrtc?.stun_servers?.length) iceServers.push({ urls: cfg.webrtc.stun_servers });
    if (cfg.webrtc?.turn) iceServers.push({ urls: cfg.webrtc.turn, username: cfg.webrtc.turn_username || undefined, credential: cfg.webrtc.turn_password || undefined });

    const pc = new RTCPeerConnection({ iceServers });

    pc.oniceconnectionstatechange = () => log('ice:', pc.iceConnectionState);
    pc.onconnectionstatechange = () => log('conn:', pc.connectionState);

    pc.ontrack = async (ev) => {
      log('ontrack track kind=', ev.track?.kind, 'readyState=', ev.track?.readyState);
      const ms = new MediaStream([ev.track]);
      video.srcObject = ms;
      try { await video.play(); log('video.play() OK'); } catch (e) { log('video.play() blocked:', e?.message || e); }
    };

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onmessage = async (msg) => {
      const data = JSON.parse(msg.data);
      if (data.type === 'offer') {
        // Server is the offerer
        await pc.setRemoteDescription({ type: 'offer', sdp: data.sdp });
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        ws.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }));
        log('answer sent');
      } else if (data.type === 'ice') {
        try { await pc.addIceCandidate({ candidate: data.candidate, sdpMLineIndex: data.sdpMLineIndex }); }
        catch (e) { log('addIce error', e?.message || e); }
      }
    };

    ws.onerror = (e) => log('ws error', e?.message || e);
    ws.onclose = () => log('ws closed');
    window._pc = pc;
  })();
})();
