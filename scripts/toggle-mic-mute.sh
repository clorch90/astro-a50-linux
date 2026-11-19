#!/bin/bash
# Toggles mute on the current default microphone and plays a distinct,
# loud two-tone sound for each state (audible even over fullscreen games).
SOUND_DIR="$HOME/.local/share/toggle-mic-mute-sounds"
wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle

if wpctl get-volume @DEFAULT_AUDIO_SOURCE@ | grep -q MUTED; then
  paplay --volume=65536 "$SOUND_DIR/mute.wav" &
else
  paplay --volume=65536 "$SOUND_DIR/unmute.wav" &
fi
