#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
APP_PATH="$APP_DIR/a50-control"
DESKTOP_PATH="$DESKTOP_DIR/io.github.astro-a50-linux.Control.desktop"

if [[ ! -x "$HOME/.local/bin/a50-battery" ]]; then
  printf 'Install the a50-battery command first.\n' >&2
  exit 1
fi

/usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' || {
  printf 'Install Python GTK4 and Libadwaita bindings for /usr/bin/python3.\n' >&2
  exit 1
}

install -Dm755 "$PROJECT_DIR/gui/a50_control.py" "$APP_PATH"
install -Dm755 "$PROJECT_DIR/scripts/a50_sidetone.py" "$APP_DIR/a50-sidetone"
install -Dm755 "$PROJECT_DIR/scripts/a50_equalizer.py" "$APP_DIR/a50-equalizer"
install -Dm644 "$PROJECT_DIR/scripts/a50_equalizer.py" "$APP_DIR/a50_equalizer.py"
install -Dm755 "$PROJECT_DIR/scripts/a50_microphone_equalizer.py" "$APP_DIR/a50-microphone-equalizer"
install -Dm755 "$PROJECT_DIR/scripts/a50_microphone_noise_gate.py" "$APP_DIR/a50-microphone-noise-gate"
install -Dm755 "$PROJECT_DIR/scripts/a50_base_station.py" "$APP_DIR/a50-base-station"
install -Dm755 "$PROJECT_DIR/scripts/a50_device_status.py" "$APP_DIR/a50-device-status"
install -d "$DESKTOP_DIR"
printf '[Desktop Entry]\nType=Application\nName=Astro A50 Control\nComment=Battery and A50 controls\nExec="%s"\nIcon=audio-headphones-symbolic\nTerminal=false\nCategories=AudioVideo;\n' \
  "$APP_PATH" > "$DESKTOP_PATH"
chmod 644 "$DESKTOP_PATH"
printf 'Installed launcher: %s\n' "$APP_PATH"
printf 'Installed desktop entry: %s\n' "$DESKTOP_PATH"
