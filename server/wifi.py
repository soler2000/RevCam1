# coding: utf-8
import os
import subprocess
import time
import shlex

NMCLI = "nmcli"
WLAN_IF = "wlan0"
AP_CON_NAME = "revcam-ap"
AP_COUNTRY = os.environ.get("REVCAM_WIFI_COUNTRY", "GB")  # change via env if needed

class WifiError(Exception):
    pass

def _run(cmd, check=True, timeout=40):
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and cp.returncode != 0:
        msg = cp.stderr.strip() or cp.stdout.strip() or ("rc=%d" % cp.returncode)
        raise WifiError("%s -> %s" % (" ".join(cmd), msg))
    return cp

def _trim(s):
    return (s or "").strip()

def _nm_fields(line, fields):
    parts = line.split(":")
    out = {}
    for i, f in enumerate(fields):
        out[f] = _trim(parts[i]) if i < len(parts) else ""
    return out

def nm_device_state():
    cp = _run([NMCLI, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], check=False)
    devs = []
    for ln in (cp.stdout or "").splitlines():
        if not ln: continue
        devs.append(_nm_fields(ln, ["device","type","state","connection"]))
    w = None
    for d in devs:
        if d.get("device")==WLAN_IF or d.get("type")=="wifi":
            w = d; break
    return {"devices": devs, "wlan": w}

def nm_active_conns():
    cp = _run([NMCLI, "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"], check=False)
    out = []
    for ln in (cp.stdout or "").splitlines():
        if not ln: continue
        out.append(_nm_fields(ln, ["name","uuid","type","device"]))
    return out

def nm_conn_mode(name):
    cp = _run([NMCLI, "-g", "802-11-wireless.mode", "connection", "show", name], check=False)
    return _trim(cp.stdout)

def nm_ip4_addr(dev=WLAN_IF):
    cp = _run([NMCLI, "-g", "IP4.ADDRESS", "device", "show", dev], check=False)
    s = _trim(cp.stdout)
    return s.split("/")[0] if s else ""

def nm_scan():
    _run([NMCLI, "radio", "wifi", "on"], check=False)
    _run(["rfkill", "unblock", "wifi"], check=False)
    _run([NMCLI, "device", "wifi", "rescan", "ifname", WLAN_IF], check=False)
    cp = _run([NMCLI, "-t", "-f", "IN-USE,SSID,SECURITY,SIGNAL,CHAN", "device", "wifi", "list", "ifname", WLAN_IF], check=False)
    nets = []
    seen = set()
    for ln in (cp.stdout or "").splitlines():
        if not ln: continue
        f = _nm_fields(ln, ["inuse","ssid","security","signal","chan"])
        if not f["ssid"]: continue
        key = (f["ssid"], f["security"])
        if key in seen: continue
        seen.add(key)
        try: f["signal"] = int(f["signal"] or "0")
        except Exception: f["signal"] = 0
        f["needs_password"] = f["security"] not in ("--", "", "NONE")
        nets.append(f)
    nets.sort(key=lambda x: x["signal"], reverse=True)
    return nets

def _iw_info():
    cp = _run(["bash","-lc","iw dev "+shlex.quote(WLAN_IF)+" info 2>/dev/null || true"], check=False)
    return (cp.stdout or "").strip()

def _nm_dev_show():
    cp = _run([NMCLI, "device", "show", WLAN_IF], check=False)
    return (cp.stdout or "").strip()

def _nm_dev_status():
    cp = _run([NMCLI, "device"], check=False)
    return (cp.stdout or "").strip()

def _verify_ap(expected_ssid, wait_ms=9000):
    deadline = time.time() + (wait_ms/1000.0)
    last = ""
    while time.time() < deadline:
        for c in nm_active_conns():
            if c.get("device") == WLAN_IF:
                name = c.get("name","")
                mode = nm_conn_mode(name)
                if mode == "ap":
                    info = _iw_info()
                    ip = nm_ip4_addr(WLAN_IF)
                    return True, "OK: active=%s mode=ap ip=%s\\niw:\\n%s" % (name, ip, info)
        info = _iw_info()
        if "type AP" in info or "type __ap" in info:
            ip = nm_ip4_addr(WLAN_IF)
            return True, "OK: iw reports AP ip=%s\\niw:\\n%s" % (ip, info)
        time.sleep(0.25); last = info
    dbg = [
        "FAILED to enter AP mode within timeout.",
        "--- nmcli device ---",
        _nm_dev_status(),
        "--- nmcli device show wlan0 ---",
        _nm_dev_show(),
        "--- iw dev wlan0 info ---",
        last or _iw_info(),
    ]
    return False, "\\n".join(dbg)

def start_open_ap(ssid="RevCam"):
    if not _exists_nmcli():
        raise WifiError("NetworkManager (nmcli) not installed/enabled")
    _run(["rfkill", "unblock", "wifi"], check=False)
    _run([NMCLI, "radio", "wifi", "on"], check=False)
    _run([NMCLI, "device", "set", WLAN_IF, "managed", "yes"], check=False)
    for c in nm_active_conns():
        if c.get("device") == WLAN_IF:
            _run([NMCLI, "connection", "down", c["name"]], check=False)
    time.sleep(1.2)
    _run([NMCLI, "connection", "delete", AP_CON_NAME], check=False)
    _run([NMCLI, "connection", "add",
          "type", "wifi",
          "ifname", WLAN_IF,
          "con-name", AP_CON_NAME,
          "ssid", ssid], check=True)
    _run([NMCLI, "connection", "modify", AP_CON_NAME,
          "802-11-wireless.country", AP_COUNTRY], check=False)
    _run([NMCLI, "connection", "modify", AP_CON_NAME,
          "802-11-wireless.mode", "ap",
          "802-11-wireless.band", "bg",
          "802-11-wireless.channel", "6",
          "802-11-wireless.hidden", "no",
          "802-11-wireless-security.key-mgmt", "none",
          "ipv4.method", "shared",
          "ipv4.addresses", "10.42.0.1/24",
          "ipv4.gateway", "10.42.0.1",
          "ipv6.method", "ignore",
          "connection.autoconnect", "no",
          "802-11-wireless.cloned-mac-address", "permanent"], check=True)
    _run([NMCLI, "connection", "up", AP_CON_NAME, "ifname", WLAN_IF], check=True, timeout=60)
    ok, diag = _verify_ap(ssid, wait_ms=9000)
    if not ok:
        _run([NMCLI, "device", "disconnect", WLAN_IF], check=False)
        time.sleep(1.0)
        _run([NMCLI, "device", "connect", WLAN_IF], check=False)
        time.sleep(0.8)
        _run([NMCLI, "connection", "up", AP_CON_NAME, "ifname", WLAN_IF], check=False, timeout=60)
        ok2, diag2 = _verify_ap(ssid, wait_ms=6000)
        if not ok2:
            raise WifiError(diag + "\\n-- Fallback also failed --\\n" + diag2)
    ip = nm_ip4_addr(WLAN_IF)
    return {"ok": True, "ap": True, "ssid": ssid, "ip": ip, "diag": diag}

def stop_ap():
    _run([NMCLI, "connection", "down", AP_CON_NAME], check=False)
    return {"ok": True}

def connect(ssid, password=None):
    if not _exists_nmcli():
        raise WifiError("NetworkManager (nmcli) not installed/enabled")
    try:
        stop_ap()
    except Exception:
        pass
    _run(["rfkill", "unblock", "wifi"], check=False)
    _run([NMCLI, "radio", "wifi", "on"], check=False)
    args = [NMCLI, "device", "wifi", "connect", ssid, "ifname", WLAN_IF]
    if password:
        args += ["password", password]
    cp = _run(args, check=True, timeout=60)
    time.sleep(1)
    return {"ok": True, "message": (cp.stdout.strip() or "connected"), "ip": nm_ip4_addr(WLAN_IF)}

def status():
    ok_nm = _exists_nmcli()
    dev = nm_device_state()
    wlan = dev.get("wlan") or {}
    state = (wlan.get("state") or "").lower()
    connected = (state == "connected")
    ssid = wlan.get("connection") if connected else ""
    mode = ""
    ap_running = False
    if connected and ssid:
        try:
            mode = nm_conn_mode(ssid)
            ap_running = (mode == "ap")
        except Exception:
            pass
    elif (wlan.get("connection") or "") == AP_CON_NAME:
        ap_running = True
        mode = "ap"
        ssid = AP_CON_NAME
    ip = nm_ip4_addr(WLAN_IF)
    return {
        "nmcli": ok_nm,
        "device": dev,
        "connected": (connected and (mode != "ap")),
        "ap_running": ap_running,
        "ssid": ssid,
        "mode": mode,
        "ip": ip,
    }

def nm_debug():
    def cmd(o):
        try:
            return _run(o, check=False).stdout.strip()
        except Exception as e:
            return "ERR: %s" % e
    return {
        "nmcli -v": cmd([NMCLI, "-v"]),
        "nmcli g status": cmd([NMCLI, "general", "status"]),
        "nmcli radio all": cmd([NMCLI, "radio", "all"]),
        "nmcli device": cmd([NMCLI, "device"]),
        "nmcli con show": cmd([NMCLI, "connection", "show"]),
        "nmcli con show --active": cmd([NMCLI, "connection", "show", "--active"]),
        "device show wlan0": cmd([NMCLI, "device", "show", WLAN_IF]),
        "iw dev wlan0 info": cmd(["bash","-lc","iw dev "+shlex.quote(WLAN_IF)+" info 2>/dev/null || true"]),
    }

class WifiManager(object):
    def __init__(self):
        self._started_ap = False
    async def watchdog_startup(self, delay_seconds=30):
        import asyncio
        try:
            await asyncio.sleep(delay_seconds)
            st = status()
            if (not st.get("connected")) and (not st.get("ap_running")):
                res = start_open_ap("RevCam")
                self._started_ap = True
                return res
        except Exception:
            pass
        return {"ok": True}

def _exists_nmcli():
    try:
        _run([NMCLI, "-v"], check=True)
        return True
    except Exception:
        return False
