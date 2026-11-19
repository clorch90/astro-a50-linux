# Astro A50 on Linux

English | [Deutsch](README.de.md)

An independent, experimental Linux configuration for the **Logitech Astro A50
Gen 5**. It provides separate Game and Voice channels, boom-arm microphone
muting, a GTK desktop app and an optional GNOME top-bar indicator.

The app and indicator offer battery and microphone status, sidetone and
equalizer controls. The app also exposes microphone EQ, noise gate and
base-station settings. Some device settings use an independently investigated
USB protocol and can change settings on the headset. Use them cautiously and
check the results on your device.

**Start here:** check the [tested environment](#tested-environment) and
[prerequisites](#prerequisites), then follow the numbered sections below.
Game/Voice, boom-arm muting, the app and the indicator can be installed
separately where indicated.

## Tested environment

| Hardware / environment | Status |
| --- | --- |
| Astro A50 Gen 5, USB ID `046d:0b1c`, firmware 1.3.24 | Tested on one device |
| Ubuntu 26.04, GNOME 50.1, PipeWire 1.6.2, WirePlumber 0.5.13 | Tested environment |
| Other A50 generations, firmware versions and Linux distributions | Untested |

Firmware version is as reported by G HUB. Device names and HID events in
particular may differ on other setups. Testing does not cover every possible
configuration or device state. Muting is
performed **in PipeWire** in response to boom-arm movement; it is not
independently verified hardware muting.

**Microphone privacy:** verify both microphone inputs are actually muted;
the boom-arm position alone is not a reliable mute indicator. See
[boom-arm muting](#2-set-up-boom-arm-muting-and-sounds).

## Prerequisites

Connect the base station to the Linux PC using its **PC USB port**, not the
Xbox or PlayStation port. The headset must not be passed through to a virtual
machine. PipeWire, WirePlumber 0.5 and PipeWire-Pulse-compatible audio output
must be running. This guide uses Python 3.10 or later and `systemd --user`.
`pavucontrol` is recommended for graphical setup.

On Ubuntu, install the required tools if needed:

```bash
sudo apt install wireplumber pipewire-bin pipewire-pulse pulseaudio-utils python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 pavucontrol usbutils
```

Check that the supported device is detected:

```bash
lsusb -d 046d:0b1c
wpctl status
```

Run the installation commands below **from the project directory**. They
overwrite existing files with the same destination names. Back up any existing
configuration files and scripts if necessary.

## 1. Set up Game and Voice

### Select the Pro Audio profile

Open `pavucontrol` and select the **Pro Audio** profile for the A50 under
**Configuration**. Alternatively, set the profile using `pactl`. First check
the actual card name:

```bash
pactl list short cards
```

If the card is named `alsa_card.usb-Logitech_A50-00`, as in the tested
environment:

```bash
pactl set-card-profile alsa_card.usb-Logitech_A50-00 pro-audio
```

The Pro Audio profile should expose two outputs and two inputs. The mapping was
verified on the tested headset using the Game/Voice mix control:

| Profile device | Purpose |
| --- | --- |
| `pro-output-0` | Voice output |
| `pro-output-1` | Game output |
| `pro-input-0` | Voice microphone |
| `pro-input-1` | Game microphone |

### Set names and default profile

The following WirePlumber configuration labels the nodes and sets the Pro
Audio profile by default for cards with the ALSA name `A50`. Restarting
WirePlumber may briefly interrupt ongoing audio playback.

```bash
install -Dm644 wireplumber/51-a50-labels.conf \
  "$HOME/.config/wireplumber/wireplumber.conf.d/51-a50-labels.conf"
systemctl --user restart wireplumber
```

Afterwards, `wpctl status` should show **A50 Voice**, **A50 Game**,
**A50 Mic (Voice)** and **A50 Mic (Game)**.

### Route applications

Start the application and open `pavucontrol`. Under **Playback**, assign its
stream to the appropriate output, for example a game to **A50 Game** and
Discord to **A50 Voice**. Under **Recording**, select the desired microphone
while the application is recording. Depending on the application, you may also
be able to select the devices in its own audio settings.

### Optional: restore silent streams after a PlaySync switch

Switching the headset to another source with PlaySync makes it disappear and
reappear. Some applications, for example Wine/Proton games, tell PipeWire not
to reconnect their stream, so they stay silent afterwards. This small user
service links such streams to the A50 output they target again:

```bash
install -Dm755 scripts/a50_relink_streams.py \
  "$HOME/.local/bin/a50-relink-streams.py"
install -Dm644 systemd/a50-relink-streams.service \
  "$HOME/.config/systemd/user/a50-relink-streams.service"
systemctl --user daemon-reload
systemctl --user enable --now a50-relink-streams.service
```

### Optional: undo profile changes made by GNOME

In the tested GNOME version, changing sound settings sometimes switched the
Pro Audio profile back to stereo. The following WirePlumber hook restores the
Pro Audio profile when the profile of an ALSA card named `A50` changes. While
the hook is installed, other profiles cannot be selected permanently for that
card.

```bash
install -Dm644 wireplumber/90-a50-lock-pro-audio.lua \
  "$HOME/.local/share/wireplumber/scripts/90-a50-lock-pro-audio.lua"
install -Dm644 wireplumber/90-a50-lock-pro-audio.conf \
  "$HOME/.config/wireplumber/wireplumber.conf.d/90-a50-lock-pro-audio.conf"
systemctl --user restart wireplumber
```

## 2. Set up boom-arm muting and sounds

On the tested device, raising and lowering the boom arm generates HID events.
The service reads these events and sets the mute state of both A50 inputs:

- Arm up: both A50 inputs muted, descending sound.
- Arm down: both A50 inputs unmuted, ascending sound – even if they were
  previously muted manually.

**Important:** At startup and after reconnecting, the arm position is unknown
until the arm is moved. The existing mute state remains unchanged until then.
Another application or keyboard shortcut can also change the mute state
independently of the arm. Do not rely on the arm position alone when you need
to be certain you are muted.

The supplied sounds are loud. Set the volume carefully before the first test.

### Check HID access

The script uses this device-specific path:

```bash
ls -l /dev/input/by-id/usb-Logitech_A50-if08-hidraw
test -r /dev/input/by-id/usb-Logitech_A50-if08-hidraw \
  && echo "HID device is readable" || echo "HID device is not readable or not present"
```

If the path is missing, check the USB connection and device ID. If it exists
but is not readable, a device-specific rule can grant access on systems with
`udev` and an active graphical session. First check that the following file
does not already exist; the command would otherwise overwrite it:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="0b1c", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/70-astro-a50-hidraw.rules
sudo udevadm control --reload-rules
```

Disconnect the headset from USB briefly, reconnect it and repeat the read
test. The rule grants the active local session access to this USB device's HID
interface. If access still fails, check your distribution's permissions and
session management instead of running the service as root.

### Install the service

```bash
install -Dm644 scripts/a50-flip-mute.py \
  "$HOME/.local/bin/a50-flip-mute.py"
install -Dm644 sounds/mute.wav \
  "$HOME/.local/share/toggle-mic-mute-sounds/mute.wav"
install -Dm644 sounds/unmute.wav \
  "$HOME/.local/share/toggle-mic-mute-sounds/unmute.wav"
install -Dm644 systemd/a50-flip-mute.service \
  "$HOME/.config/systemd/user/a50-flip-mute.service"
systemctl --user daemon-reload
systemctl --user enable --now a50-flip-mute.service
```

The service expects the PipeWire node names
`alsa_input.usb-Logitech_A50-00.pro-input-0` and
`alsa_input.usb-Logitech_A50-00.pro-input-1`. If they differ on your system,
automatic muting with this script will not work without adjustment.

### Verify operation

Raise and lower the arm. Check that you hear both sounds and that the A50
inputs' mute state changes accordingly:

```bash
wpctl status
systemctl --user status a50-flip-mute.service
journalctl --user -u a50-flip-mute.service -n 30 --no-pager
```

The current IDs are shown in `wpctl status`; they may change after a restart
or reconnection. Use `wpctl get-volume ID` to check whether `[MUTED]` is shown
for each input. Replace `ID` with the corresponding current number.

### Optional: keyboard shortcut

This separate script toggles **the current default microphone** and plays the
same sounds. Unlike the boom-arm service, it does not automatically control
both A50 inputs.

```bash
install -Dm755 scripts/toggle-mic-mute.sh \
  "$HOME/.local/bin/toggle-mic-mute.sh"
```

In GNOME, create a shortcut under **Settings → Keyboard → Keyboard Shortcuts →
Custom Shortcuts**. Enter the full path to the installed script as the command,
for example `/home/YOUR_USER/.local/bin/toggle-mic-mute.sh`. **Numpad Plus**
was tested as the shortcut key.

## 3. Check battery status

The experimental command below sends one battery request observed from G HUB
and prints a single result; it does not run in the background. The same
[device protocol has also been documented by HaloBattery](https://github.com/HeyOkay/HaloBattery/blob/main/docs/protocols.md#astro-a50-gen-5-logitech-046d0b1c).

The headset reports two values. In our tests G HUB matched the first value
while undocked and the second while charging, so the command uses that rule
as an **estimate** and prints both reported values for comparison. Their
meaning is not fully verified, the values can differ, and a disconnected or
powered-off headset may report stale information. Do not treat the displayed
percentage as definitive.

The HID device must be both readable **and writable** by the current user.
Check the permissions as described in the HID access section above; replace
`test -r` with `test -w` to check write access. The headset must be connected
to Linux, not passed through to a virtual machine.

```bash
install -Dm755 scripts/a50_battery.py "$HOME/.local/bin/a50-battery"
"$HOME/.local/bin/a50-battery"
```

The command reports errors if the device cannot be opened, does not answer, or
returns unrecognized values. It sends a request only when run; it does not
change the boom-arm service. Battery and other device requests share a
non-blocking lock; if another request is in progress, retry after it finishes.
The lock requires `XDG_RUNTIME_DIR`, normally set in a graphical user session.

### Experimental sidetone control

The sidetone control is experimental and tested only with firmware 1.3.24.
The headset uses seven levels, from 0 to 6. G HUB's USB commands for all seven
levels were captured. The command for level 1 and the reset to level 0 were
also tested under Linux.
The desktop app reads the level on opening, displays it as a percentage and
automatically applies slider changes. The GNOME extension also displays
percentages and applies changes on slider release, or after a short pause for
keyboard and scroll input; it does not read the level. The seven device levels
correspond to approximately 0, 17, 33, 50, 67, 83 and 100%.

Install the shared command before using the extension or the app:

```bash
install -Dm755 scripts/a50_sidetone.py "$HOME/.local/bin/a50-sidetone"
```

Changing sidetone requires the same HID access as the battery command.
The headset must be connected to Linux, not passed through to a VM. Errors are
shown in the app or in the GNOME indicator and logged by GNOME Shell.

### Experimental equalizer

The headset EQ is experimental and tested with firmware 1.3.24. The profile
contains ten bands from 20 Hz to 20 kHz. The editor supports −6 to +6 dB in
0.5 dB steps. The desktop app reads the EQ curve on opening without changing
it; it does not identify the active preset name directly.

The app selects a preset name when exactly one saved curve matches; it does
not read the active preset name from the headset. **Standard** is the
neutral profile; there is no separate duplicate **Flat** preset. **Bass**,
**Voice** and **Footsteps** are original starting points. Custom
presets can be saved in the desktop editor and are stored in
`~/.config/astro-a50-linux/eq-presets.json`. The command is also available
directly:

```bash
install -Dm755 scripts/a50_equalizer.py "$HOME/.local/bin/a50-equalizer"
"$HOME/.local/bin/a50-equalizer" list
"$HOME/.local/bin/a50-equalizer" apply "Standard"
```

Applying a profile changes the headset EQ. Use it only with the headset
connected to Linux and HID write access configured. The response confirms that
the profile was accepted but does not read back the current EQ.

### Separate microphone equalizer

The microphone EQ is an independent experimental control path, separate from
the playback EQ. User-owned USB captures confirm ten bands at 80 Hz, 150 Hz,
250 Hz, 400 Hz, 800 Hz, 1.5 kHz, 2.5 kHz, 5 kHz, 10 kHz and 19 kHz. The
confirmed range is −6 to +6 dB in 0.5 dB steps. **Standard** is neutral;
**Warm** and **Klar** are original starting points, not acoustically
calibrated profiles.

The desktop app has its own full microphone EQ editor and custom presets,
separate from playback EQ. They are stored in
`~/.config/astro-a50-linux/microphone-eq-presets.json`. The desktop app reads
the microphone EQ curve on opening without changing it.

### Microphone noise gate

A separate capture confirms the mapping **Aus** (`0`), **Nacht** (`2`),
**Zu Hause** (`1`) and **Turnier** (`4`). Noise-gate and microphone EQ curves
use different commands. For example:

```bash
install -Dm755 scripts/a50_microphone_noise_gate.py \
  "$HOME/.local/bin/a50-microphone-noise-gate"
install -Dm644 scripts/a50_equalizer.py "$HOME/.local/bin/a50_equalizer.py"
"$HOME/.local/bin/a50-microphone-noise-gate" list
"$HOME/.local/bin/a50-microphone-noise-gate" set "Nacht"
```

The desktop app provides controls without setting a state on opening.
A successful command receives a device acknowledgement,
but that acknowledgement does not itself read back the active or stored state.
The desktop app reads the state separately on opening; **Nacht** and **Aus**
were verified under Linux.

### Base-station and device settings

User-owned captures show base-station brightness at 50 and 100 and sleep
timeouts of **Off**, 15, 30 and 60 minutes. The sound modes **All**, **Minimal**
and **Off** were also captured. A successful write acknowledgement does not
read back the stored setting. The desktop app separately reads brightness,
sleep timeout and sound mode on opening.

Bluetooth is displayed, not switched. Its status query distinguishes a
connected device from no connection and can display the device name reported
by the headset. The `a50-base-station` command can be used directly. Install it and its shared
module first, unless the desktop app has already installed them:

```bash
install -Dm755 scripts/a50_base_station.py "$HOME/.local/bin/a50-base-station"
install -Dm644 scripts/a50_equalizer.py "$HOME/.local/bin/a50_equalizer.py"
"$HOME/.local/bin/a50-base-station" brightness 50
"$HOME/.local/bin/a50-base-station" sleep 30
"$HOME/.local/bin/a50-base-station" sound minimal
"$HOME/.local/bin/a50-base-station" bluetooth
```

### Optional: GNOME top-bar indicator

The included extension is tested with GNOME Shell 50. It uses the installed
`a50-battery` command and queries the headset once when enabled and then every
60 seconds. You can also refresh it from the indicator menu. The battery icon
is green while charging, darker green when full, red at 20% or less and orange
from 21% through 40%; otherwise it uses the GNOME theme color. The displayed
percentage is experimental and may not be exact. A microphone icon in the top bar shows the live
mute state; open the menu and activate the microphone row to toggle both A50
inputs. Mixed input states use a neutral icon, and toggling mutes both. The
microphone state is refreshed every two seconds. A question mark or neutral
microphone icon appears if a request fails; an off or disconnected headset can
still return stale battery data. On the tested setup, charging, not charging
and disconnected states were checked in the top bar and behaved as expected.
The menu also contains the experimental sidetone slider,
as well as quick access to the built-in EQ presets and read-only Bluetooth
status. Install `a50-battery`, `a50-sidetone`, `a50-equalizer` and
`a50-base-station` using the sections above; the Bluetooth helper also
requires the shared `a50_equalizer.py` module. Alternatively, install
`a50-battery` and then the desktop app, whose installer installs the other
helpers. Microphone EQ, noise gate, brightness, sleep timeout and sounds
remain in the desktop app.

After installing the battery command above, run these commands from the project
directory:

```bash
gnome-extensions pack --extra-source=status.js \
  gnome-extension/a50-battery@astro-a50-linux
gnome-extensions install -f a50-battery@astro-a50-linux.shell-extension.zip
gnome-extensions enable a50-battery@astro-a50-linux
```

The packaging command creates a ZIP file in the current directory and does not
overwrite an existing package by default. When updating an already installed
extension, disable it before installing and enable it afterwards. If GNOME
does not immediately load an update, sign out and back in:

```bash
gnome-extensions disable a50-battery@astro-a50-linux
gnome-extensions install -f a50-battery@astro-a50-linux.shell-extension.zip
gnome-extensions enable a50-battery@astro-a50-linux
```

Check its status or disable it with:

```bash
gnome-extensions info a50-battery@astro-a50-linux
gnome-extensions disable a50-battery@astro-a50-linux
```

## 4. Small desktop app

The GTK4/Libadwaita app uses a generic GNOME headphones symbol instead of a
manufacturer product image. It shows battery and microphone status, a
sidetone slider, and separate full 10-band editors for playback EQ and
microphone EQ. The left menu opens the **Settings** start page with device
options and separate **Output EQ** and **Microphone EQ** pages. Battery and
microphone controls remain visible in the header. Each editor has its own
presets and custom preset storage.
Slider and selection changes are applied automatically after a short pause;
saving still creates a custom preset. Opening the app reads sidetone,
brightness, sleep timeout, sound mode, noise gate and both EQ curves without
writing settings. The EQ selector shows a preset when its curve matches, but
the active preset name itself is not read back. Multiple matches and custom
curves are indicated separately. The
microphone control toggles both inputs together; if they are in different
states, clicking mutes both.

The app checks microphone state every two seconds and battery status every 60
seconds. Device checks run in worker threads. Install the system Python GTK4
and Libadwaita bindings if they are not already available:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Install the app and its application-menu entry from the project directory:

```bash
scripts/install-gui.sh
```

Launch **Astro A50 Control** from the app grid, or run
`~/.local/bin/a50-control`. The installer includes the sidetone, EQ and other
device commands. The app uses the already-installed
`~/.local/bin/a50-battery` command and the mute/unmute sounds installed in
section 2. It does not change the boom-arm service.

## Known limitations

- This is an initial configuration tested on one device, not general support
  for all A50 models.
- The boom-arm service only reads from the HID device. It does not query the
  current arm position.
- The battery reading is experimental. PLAYSYNC control and firmware updates
  are not implemented here. Firmware updates have so far been performed using
  G HUB on Windows.

## Updating and removal

To update, replace the project files and repeat only the installation steps
for the components you use. Install commands overwrite their destination
files; back up local modifications first. Restart installed user services with
`systemctl --user restart a50-flip-mute.service` or
`systemctl --user restart a50-relink-streams.service`, as applicable. Update
the extension as described above and sign out and back in if necessary.

To remove components, first stop and disable each installed user service with
`systemctl --user disable --now SERVICE`, substituting
`a50-flip-mute.service` or `a50-relink-streams.service`. Uninstall the
extension with `gnome-extensions uninstall a50-battery@astro-a50-linux`.
Then, if no longer needed, remove the corresponding installed files listed in
the installation commands, the desktop entry
`~/.local/share/applications/io.github.astro-a50-linux.Control.desktop`, and
the service files in `~/.config/systemd/user/`; run
`systemctl --user daemon-reload` after removing service files. Remove the
installed WirePlumber configuration and hook only if you installed them for
this project, then restart WirePlumber. Remove the optional udev rule only if
you created it for this project, reload udev rules and reconnect the device.
The GUI installer places `a50-control`, `a50-sidetone`, `a50-equalizer`,
`a50_equalizer.py`, `a50-microphone-equalizer`, `a50-microphone-noise-gate`,
`a50-base-station` and `a50-device-status` in `~/.local/bin/`. Remove a helper
only when no remaining component needs it.
The custom presets under `~/.config/astro-a50-linux/` are not removed by these
steps; back them up or remove them separately if desired. Changes already sent
to the headset are not automatically reverted.

## Tests

From the project directory, with the Python GTK/Libadwaita bindings and GJS
installed:

```bash
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'
gjs -m tests/test_a50_indicator.js
```

GTK-dependent tests may be skipped when no graphical display is available.
The automated tests use mocks and do not replace testing on the device.

## License and trademarks

The project code is licensed under the GNU General Public License, version 3
or any later version (GPL-3.0-or-later); see [LICENSE](LICENSE).

Logitech, Astro, A50 and G HUB are names or trademarks of their respective
owners; their use here identifies compatible products. This independent
project is not affiliated with or endorsed by Logitech.
