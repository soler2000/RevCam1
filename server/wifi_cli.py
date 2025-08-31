from __future__ import annotations
import sys, json
from .wifi import start_open_ap, stop_ap, status, nm_debug, connect as wifi_connect

def main(argv):
    if len(argv) < 2:
        print("Usage: python -m server.wifi_cli <start-ap [ssid]|stop-ap|status|debug|connect <ssid> [password]>")
        return 2
    cmd = argv[1]
    try:
        if cmd == "start-ap":
            ssid = argv[2] if len(argv) > 2 else "RevCam"
            res = start_open_ap(ssid)
            print(json.dumps(res, indent=2))
            return 0
        elif cmd == "stop-ap":
            print(json.dumps(stop_ap(), indent=2)); return 0
        elif cmd == "status":
            print(json.dumps(status(), indent=2)); return 0
        elif cmd == "debug":
            print(json.dumps(nm_debug(), indent=2)); return 0
        elif cmd == "connect":
            if len(argv) < 3: 
                print("connect needs SSID [password]"); return 2
            ssid = argv[2]; pwd = argv[3] if len(argv) > 3 else None
            print(json.dumps(wifi_connect(ssid, pwd), indent=2)); return 0
        else:
            print("Unknown command"); return 2
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)} , indent=2))
        return 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
