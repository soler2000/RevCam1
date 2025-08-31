#!/usr/bin/env bash
set -e

sudo apt-get update
sudo apt-get -y upgrade

# Camera stack
sudo apt-get -y install libcamera-apps

# GStreamer + GI + plugins (WebRTC + libcamera)
sudo apt-get -y install \
  python3-gi python3-gi-cairo gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl \
  gstreamer1.0-libcamera gstreamer1.0-nice gstreamer1.0-nice gstreamer1.0-nice

sudo apt-get -y install v4l-utils
sudo usermod -a -G video "$USER"
echo "Install complete. Create venv and pip install -r requirements.txt."
