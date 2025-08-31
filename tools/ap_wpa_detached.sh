#!/usr/bin/env bash
set -euo pipefail
SSID="${1:-RevCam}"; PASS="${2:-RevCam1234}"
LOG="/tmp/revcam_ap_run.log"
{
  echo ">>> $(date) starting AP SSID='$SSID' WPA2-PSK"
  # Align regulatory domain (adjust 'GB' if needed)
  sudo iw reg set GB || true
  sudo raspi-config nonint do_wifi_country GB || true

  # Hand wlan0 to NetworkManager, drop STA, create fresh AP profile
  sudo nmcli radio wifi on
  sudo nmcli device set wlan0 managed yes
  sudo nmcli --wait 2 connection down preconfigured || true
  sudo nmcli connection delete revcam-ap || true
  sudo nmcli connection add type wifi ifname wlan0 con-name revcam-ap ssid "$SSID"

  # WPA2 AP on 2.4GHz ch6, shared IPv4 @ 10.42.0.1
  sudo nmcli connection modify revcam-ap \
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

  # Bring AP up and show state
  sudo nmcli connection up revcam-ap ifname wlan0
  echo ">>> iw dev wlan0 info:"
  iw dev wlan0 info || true
  echo ">>> ip addr wlan0:"
  ip -4 addr show wlan0 || true
  echo ">>> AP up. Join SSID '$SSID' (pass: $PASS). Open http://10.42.0.1:8080"
} > "$LOG" 2>&1 &
disown
echo "Started detached. Log: $LOG"
