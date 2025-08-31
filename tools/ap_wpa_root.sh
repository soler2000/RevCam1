#!/usr/bin/env bash
set -euxo pipefail
SSID="${1:-RevCam}"
PASS="${2:-RevCam1234}"
LOG="/tmp/revcam_ap_run.log"

{
  echo "=== $(date) RevCam AP bring-up (WPA2) ==="
  echo "SSID=$SSID PASS=$PASS"

  # Ensure regulatory domain is consistent
  iw reg set GB || true
  raspi-config nonint do_wifi_country GB || true

  # Make sure NM manages wlan0 and Wi-Fi radio is on
  nmcli -g STATE general
  nmcli radio wifi on || true
  nmcli device set wlan0 managed yes || true

  # Drop any current STA connection on wlan0
  nmcli --wait 2 connection down preconfigured || true

  # Remove stale AP profile, then create fresh
  nmcli connection delete revcam-ap || true
  nmcli connection add type wifi ifname wlan0 con-name revcam-ap ssid "$SSID"

  # Configure WPA2 AP on 2.4GHz ch6 with IPv4 shared @ 10.42.0.1
  nmcli connection modify revcam-ap \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel 6 \
    802-11-wireless.country GB \
    802-11-wireless.hidden no \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$PASS" \
    ipv4.method shared \
    ipv4.addresses 10.42.0.1/24 \
    ipv4.gateway 10.42.0.1 \
    ipv6.method ignore \
    connection.autoconnect no

  # Bring AP up
  nmcli connection up revcam-ap ifname wlan0

  # Verify
  echo "--- iw dev wlan0 info ---"
  iw dev wlan0 info || true
  echo "--- ip addr wlan0 ---"
  ip -4 addr show wlan0 || true
  echo "AP should be up. Join SSID '$SSID' (pass: $PASS), then open http://10.42.0.1:8080"
} >"$LOG" 2>&1
