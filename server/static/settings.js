(async function(){
  const form = document.getElementById('form');
  const statusEl = document.getElementById('status');
  const setStatus = s => statusEl.textContent = s;
  const toList = s => s.split(',').map(x=>x.trim()).filter(Boolean);

  async function load(){
    const r = await fetch('/api/config');
    const cfg = await r.json();
    document.getElementById('width').value = cfg.video.width;
    document.getElementById('height').value = cfg.video.height;
    document.getElementById('fps').value = cfg.video.fps;
    document.getElementById('bitrate').value = cfg.video.bitrate;
    document.getElementById('flip').value = cfg.video.flip;
    document.getElementById('stun').value = (cfg.webrtc.stun_servers||[]).join(', ');
    document.getElementById('turn').value = cfg.webrtc.turn || '';
    document.getElementById('turn_user').value = cfg.webrtc.turn_username || '';
    document.getElementById('turn_pass').value = cfg.webrtc.turn_password || '';
    document.getElementById('host').value = cfg.server.host;
    document.getElementById('port').value = cfg.server.port;
  }

  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const body = {
      video: {
        width: +document.getElementById('width').value,
        height: +document.getElementById('height').value,
        fps: +document.getElementById('fps').value,
        bitrate: +document.getElementById('bitrate').value,
        flip: document.getElementById('flip').value,
      },
      webrtc: {
        stun_servers: toList(document.getElementById('stun').value),
        turn: document.getElementById('turn').value,
        turn_username: document.getElementById('turn_user').value,
        turn_password: document.getElementById('turn_pass').value,
      },
      server: {
        host: document.getElementById('host').value,
        port: +document.getElementById('port').value,
      }
    };
    const r = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const ok = (await r.json()).ok;
    setStatus(ok ? 'saved' : 'error');
  });

  load().catch(e=>setStatus('load error: ' + e.message));
})();
