#!/usr/bin/env bash
set -euo pipefail
LOG="${HOME}/RevCam1/tools/ap_debug_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "=== RevCam1 AP debug $(date) ==="
echo "Log: $LOG"

SSID="${1:-RevCam}"
COUNTRY="${COUNTRY:-GB}"       # change if you’re not in the UK
IFACE="${IFACE:-wlan0}"
AP_NAME="revcam-ap"

echo "--- System & RF state ---"
uname -a
. /etc/os-release; echo "OS: $PRETTY_NAME"
rfkill list || true
iw dev || true
echo "--- Supported interface modes (iw list) ---"
iw list 2>/dev/null | sed -n '/Supported interface modes:/,/software interface modes:/p' || true
echo "--- NetworkManager ---"
nmcli -v || true
systemctl is-active NetworkManager || true
nmcli radio all || true
nmcli device || true
nmcli connection show || true
nmcli connection show --active || true
echo "--- NM config snippets ---"
grep -RIn 'managed\|unmanage\|wifi' /etc/NetworkManager 2>/dev/null || true
ps -ef | egrep -i 'wpa_supplicant|iwd' || true
systemctl is-active iwd || true

echo
echo "== Ensure regulatory domain & radio on =="
sudo raspi-config nonint do_wifi_country "$COUNTRY" || true
rfkill unblock wifi || true
nmcli radio wifi on || true
nmcli device set "$IFACE" managed yes || true

echo
echo "== Bring down any active Wi-Fi on $IFACE =="
for n in $(nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v ifc="$IFACE" '$2==ifc{print $1}'); do
  echo "down $n"
  nmcli connection down "$n" || true
done

echo
echo "== Remove stale AP profile and create fresh =="
nmcli connection delete "$AP_NAME" || true
nmcli connection add type wifi ifname "$IFACE" con-name "$AP_NAME" ssid "$SSID"
nmcli connection modify "$AP_NAME" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel 6 \
  802-11-wireless.hidden no \
  802-11-wireless-security.key-mgmt none \
  ipv4.method shared \
  ipv4.addresses 10.42.0.1/24 \
  ipv4.gateway 10.42.0.1 \
  ipv6.method ignore \
  connection.autoconnect no \
  802-11-wireless.cloned-mac-address permanent || true

echo
echo "== Bring AP up (this may drop SSH) =="
(set +e; nmcli connection up "$AP_NAME" ifname "$IFACE"; echo "nmcli up rc=$?") || true

echo
echo "== Verify AP mode for up to 10s =="
for i in {1..20}; do
  echo "check $i"
  iw dev "$IFACE" info 2>/dev/null || true
  MODE_LINE="$(iw dev "$IFACE" info 2>/dev/null | grep -E 'type (AP|__ap)' || true)"
  if [[ -n "$MODE_LINE" ]]; then
    IP=$(nmcli -g IP4.ADDRESS device show "$IFACE" 2>/dev/null | head -n1 | cut -d/ -f1)
    echo "AP OK: $MODE_LINE  IP=$IP"
    echo "Join SSID '${SSID}' then browse http://10.42.0.1:8080/wifi"
    exit 0
  fi
  sleep 0.5
done

echo
echo "== AP not up; dump NM + kernel logs =="
nmcli device || true
nmcli connection show --active || true
ip a show "$IFACE" || true
journalctl -u NetworkManager -n 100 --no-pager || true
dmesg | tail -n 100 || true

echo "AP FAILED. Review log: $LOG"
exit 1
