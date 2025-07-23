#!/bin/bash
# to be copied in /usr/local/bin/switch-display.sh
# chmod +x /usr/local/bin/switch-display.sh
# Wait for 10 seconds to ensure HDMI is initialized
sleep 10

# Check connected displays
HDMI_STATUS=$(cat /sys/class/drm/card1-HDMI-A-1/status)

if [ "$HDMI_STATUS" = "connected" ]; then
  # If yes, disable the dummy driver configuration by renaming the file
  if [ -f /usr/share/X11/xorg.conf.d/xorg.conf ]; then
    sudo mv /usr/share/X11/xorg.conf.d/xorg.conf /usr/share/X11/xorg.conf.d/xorg.conf.bak
    echo "HDMI connected. Dummy driver configuration disabled."
  else
    echo "HDMI connected, but xorg.conf does not exist."
  fi
else
  # If no, enable the dummy driver configuration by restoring the file
  if [ -f /usr/share/X11/xorg.conf.d/xorg.conf.bak ]; then
    sudo mv /usr/share/X11/xorg.conf.d/xorg.conf.bak /usr/share/X11/xorg.conf.d/xorg.conf
    sudo X :1 -config /usr/share/X11/xorg.conf.d/xorg.conf &
    echo "HDMI not connected. Dummy driver configuration enabled."
  else
    echo "HDMI not connected, but xorg.conf.bak does not exist."
  fi
fi
