#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="a50-battery@astro-a50-linux"
HID="/dev/input/by-id/usb-Logitech_A50-if08-hidraw"
UDEV_RULE="/etc/udev/rules.d/70-astro-a50-hidraw.rules"
BIN="$HOME/.local/bin"
SOUNDS="$HOME/.local/share/toggle-mic-mute-sounds"
SERVICES="$HOME/.config/systemd/user"
WP_CONFIG="$HOME/.config/wireplumber/wireplumber.conf.d"
ask() {
  local answer
  while true; do
    printf '%s [y/N]: ' "$1"
    if ! IFS= read -r answer; then
      printf '\n%s\n' 'Input ended; setup cancelled.' >&2
      exit 1
    fi
    case "$answer" in
      y|Y|j|J|yes|YES|ja|JA) return 0 ;;
      n|N|no|NO|nein|NEIN|"") return 1 ;;
      *) printf '%s\n' 'Please answer yes or no.' ;;
    esac
  done
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing program: %s\n' "$1" >&2
    exit 1
  fi
}

if [[ $# -ne 0 ]]; then
  printf '%s\n' 'This interactive setup accepts no arguments.' >&2
  exit 1
fi
if [[ $EUID -eq 0 ]]; then
  printf '%s\n' 'Run setup as your normal user, not with sudo.' >&2
  exit 1
fi

printf '%s\n' 'Astro A50 setup: experimental; tested on Ubuntu 26.04, GNOME 50 and A50 Gen 5 (046d:0b1c).'
printf '%s\n' 'Packages are not installed automatically. See the README for prerequisites.'
printf '%s\n' 'The boom arm controls PipeWire inputs; arm position alone does not guarantee muting.'

labels=false
lock_profile=false
relink=false
boom=false
gui=false
extension=false
udev=false
ask 'Install Game/Voice labels and the Pro Audio default profile? WirePlumber will restart.' && labels=true
ask 'Lock the A50 to Pro Audio? Other profiles cannot be selected permanently.' && lock_profile=true
ask 'Install and start the optional PlaySync reconnect service?' && relink=true
ask 'Install and start the boom-arm mute service and sounds?' && boom=true
ask 'Install the desktop app?' && gui=true
ask 'Install and enable the GNOME top-bar extension?' && extension=true
if $boom || $gui || $extension; then
  printf '%s\n' 'The optional udev rule grants the active local session access to the A50 HID device and requires sudo.'
  if [[ -e "$UDEV_RULE" || -L "$UDEV_RULE" ]]; then
    printf 'Existing udev rule will not be changed: %s\n' "$UDEV_RULE"
  elif ask 'Create the udev rule and reload rules? Reconnect the headset afterwards.'; then
    udev=true
  fi
  if [[ ! -e "$HID" ]]; then
    printf 'Headset HID device is currently absent: %s\n' "$HID"
  elif [[ ! -r "$HID" || ! -w "$HID" ]]; then
    printf '%s\n' 'HID access is currently restricted; see the README for permission checks.'
  fi
fi

if ! $labels && ! $lock_profile && ! $relink && ! $boom && ! $gui && ! $extension && ! $udev; then
  printf '%s\n' 'Nothing selected; no changes made.'
  exit 0
fi

require_command install
if $labels || $lock_profile || $relink || $boom; then
  require_command systemctl
  if ! systemctl --user show-environment >/dev/null; then
    printf '%s\n' 'The systemd user session is unavailable.' >&2
    exit 1
  fi
fi
if $boom || $gui || $extension; then
  for command in wpctl pw-dump paplay; do require_command "$command"; done
fi
if $relink || $boom || $gui || $extension; then
  if [[ ! -x /usr/bin/python3 ]]; then
    printf '%s\n' '/usr/bin/python3 is required.' >&2
    exit 1
  fi
fi
if $relink; then
  for command in pw-dump pw-link; do require_command "$command"; done
fi
if $gui && ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")'; then
  printf '%s\n' 'Python GTK4 and Libadwaita bindings are required; see the README.' >&2
  exit 1
fi
if $extension; then
  require_command gnome-extensions
  require_command gnome-shell
  shell_version="$(gnome-shell --version)"
  if [[ ! "$shell_version" =~ ^GNOME[[:space:]]Shell[[:space:]]50([.]|$) ]]; then
    printf 'Extension supports GNOME Shell 50 only: %s\n' "$shell_version" >&2
    exit 1
  fi
fi
if $udev; then
  require_command sudo
  require_command udevadm
fi

files=()
add_file() { files+=("$1"); }
if $labels; then add_file "$WP_CONFIG/51-a50-labels.conf"; fi
if $lock_profile; then
  add_file "$WP_CONFIG/90-a50-lock-pro-audio.conf"
  add_file "$HOME/.local/share/wireplumber/scripts/90-a50-lock-pro-audio.lua"
fi
if $relink; then
  add_file "$BIN/a50-relink-streams.py"
  add_file "$SERVICES/a50-relink-streams.service"
fi
if $boom; then
  add_file "$BIN/a50-flip-mute.py"
  add_file "$SERVICES/a50-flip-mute.service"
fi
if $boom || $gui || $extension; then
  add_file "$SOUNDS/mute.wav"
  add_file "$SOUNDS/unmute.wav"
fi
if $gui || $extension; then
  for name in a50-battery a50-sidetone a50-equalizer a50_equalizer.py a50-base-station; do add_file "$BIN/$name"; done
fi
if $gui; then
  for name in a50-control a50-microphone-equalizer a50-microphone-noise-gate a50-device-status; do add_file "$BIN/$name"; done
  add_file "$HOME/.local/share/applications/io.github.astro-a50-linux.Control.desktop"
fi

conflicts=false
for file in "${files[@]}"; do
  if [[ -L "$file" || ( -e "$file" && ! -f "$file" ) ]]; then
    printf 'Destination is not a regular file; setup aborted: %s\n' "$file" >&2
    exit 1
  fi
  if [[ -e "$file" ]]; then
    if ! $conflicts; then
      printf '%s\n' 'These existing files would be overwritten:'
      conflicts=true
    fi
    printf '  %s\n' "$file"
  fi
done
if $conflicts && ! ask 'Overwrite these files? Back up local changes first.'; then
  printf '%s\n' 'No files changed.'
  exit 0
fi

extension_installed=false
if $extension && gnome-extensions info "$UUID" >/dev/null 2>&1; then
  extension_installed=true
  printf '%s\n' 'An extension with this UUID is already installed and will be replaced.'
  if ! ask 'Replace the extension?'; then
    printf '%s\n' 'No files changed.'
    exit 0
  fi
fi

if ! ask 'Apply the selected changes now?'; then
  printf '%s\n' 'No files changed.'
  exit 0
fi

trap 'printf "%s\n" "Setup failed; some changes may already have been made." >&2' ERR

if $udev; then
  sudo sh -c 'set -C; printf "%s\n" '"'"'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="0b1c", TAG+="uaccess"'"'"' > "$1"' sh "$UDEV_RULE"
  sudo udevadm control --reload-rules
  printf '%s\n' 'udev rule created. Reconnect the headset and check HID access.'
fi
if $labels; then
  install -Dm644 "$PROJECT_DIR/wireplumber/51-a50-labels.conf" "$WP_CONFIG/51-a50-labels.conf"
fi
if $lock_profile; then
  install -Dm644 "$PROJECT_DIR/wireplumber/90-a50-lock-pro-audio.conf" "$WP_CONFIG/90-a50-lock-pro-audio.conf"
  install -Dm644 "$PROJECT_DIR/wireplumber/90-a50-lock-pro-audio.lua" "$HOME/.local/share/wireplumber/scripts/90-a50-lock-pro-audio.lua"
fi
if $relink; then
  install -Dm755 "$PROJECT_DIR/scripts/a50_relink_streams.py" "$BIN/a50-relink-streams.py"
  install -Dm644 "$PROJECT_DIR/systemd/a50-relink-streams.service" "$SERVICES/a50-relink-streams.service"
fi
if $boom; then
  install -Dm644 "$PROJECT_DIR/scripts/a50-flip-mute.py" "$BIN/a50-flip-mute.py"
  install -Dm644 "$PROJECT_DIR/systemd/a50-flip-mute.service" "$SERVICES/a50-flip-mute.service"
fi
if $boom || $gui || $extension; then
  install -Dm644 "$PROJECT_DIR/sounds/mute.wav" "$SOUNDS/mute.wav"
  install -Dm644 "$PROJECT_DIR/sounds/unmute.wav" "$SOUNDS/unmute.wav"
fi
if $gui || $extension; then
  install -Dm755 "$PROJECT_DIR/scripts/a50_battery.py" "$BIN/a50-battery"
  if $gui; then
    "$PROJECT_DIR/scripts/install-gui.sh"
  else
    install -Dm755 "$PROJECT_DIR/scripts/a50_sidetone.py" "$BIN/a50-sidetone"
    install -Dm755 "$PROJECT_DIR/scripts/a50_equalizer.py" "$BIN/a50-equalizer"
    install -Dm644 "$PROJECT_DIR/scripts/a50_equalizer.py" "$BIN/a50_equalizer.py"
    install -Dm755 "$PROJECT_DIR/scripts/a50_base_station.py" "$BIN/a50-base-station"
  fi
fi
if $labels || $lock_profile; then systemctl --user restart wireplumber; fi
if $relink || $boom; then
  systemctl --user daemon-reload
  if $relink; then
    systemctl --user enable a50-relink-streams.service
    systemctl --user restart a50-relink-streams.service
  fi
  if $boom; then
    systemctl --user enable a50-flip-mute.service
    systemctl --user restart a50-flip-mute.service
  fi
fi
if $extension; then
  package_dir="$(mktemp -d)"
  package="$package_dir/$UUID.shell-extension.zip"
  trap 'rm -f -- "$package"; rmdir -- "$package_dir"' EXIT
  gnome-extensions pack --extra-source=status.js --out-dir "$package_dir" "$PROJECT_DIR/gnome-extension/$UUID"
  if $extension_installed; then gnome-extensions disable "$UUID"; fi
  if ! gnome-extensions install -f "$package"; then
    if $extension_installed; then
      gnome-extensions enable "$UUID" || printf '%s\n' "Could not re-enable $UUID" >&2
    fi
    printf '%s\n' 'Extension installation failed.' >&2
    exit 1
  fi
  gnome-extensions enable "$UUID"
  printf '%s\n' 'If the extension does not load, sign out and back in.'
fi
printf '%s\n' 'Setup complete. Verify device access and microphone muting as described in the README.'
