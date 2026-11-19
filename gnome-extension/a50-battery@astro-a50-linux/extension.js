import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Slider from 'resource:///org/gnome/shell/ui/slider.js';

import {
    batteryIcon,
    batteryColor,
    microphoneIcon,
    parseMicrophoneStatus,
    parseStatus,
    SidetoneController,
    sidetoneLevel,
    sidetonePercent,
    toggledMicrophoneMute,
} from './status.js';

const POLL_SECONDS = 60;
const MICROPHONE_POLL_SECONDS = 2;
const EQ_PRESETS = ['Standard', 'Bass', 'Voice', 'Footsteps'];

export default class A50BatteryExtension extends Extension {
    enable() {
        this._disposed = false;
        this._process = null;
        this._micProcess = null;
        this._lastError = null;
        this._lastMicError = null;
        this._micBusy = false;
        this._eqBusy = false;
        this._bluetoothBusy = false;
        this._lastBluetoothError = null;
        this._german = GLib.get_language_names().some(name => name.startsWith('de'));
        this._indicator = new PanelMenu.Button(0.0, 'Astro A50 Battery', false);
        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            icon_name: 'battery-missing-symbolic',
            style_class: 'system-status-icon',
        });
        this._micIcon = new St.Icon({
            icon_name: 'audio-input-microphone-symbolic',
            style_class: 'system-status-icon',
        });
        this._label = new St.Label({
            text: 'A50 ?',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._label);
        box.add_child(this._micIcon);
        this._indicator.add_child(box);

        this._micToggleItem = new PopupMenu.PopupMenuItem(
            this._text('Mikrofon wird geprüft', 'Checking microphone'));
        this._micToggleItem.setSensitive(false);
        this._micToggleItem.connect('activate', () => this._toggleMicrophone());
        this._indicator.menu.addMenuItem(this._micToggleItem);
        this._details = new PopupMenu.PopupMenuItem(
            this._text('Akku nicht verfügbar', 'Battery unavailable'),
            {reactive: false, can_focus: false});
        this._indicator.menu.addMenuItem(this._details);
        this._sidetoneStatus = new PopupMenu.PopupMenuItem(
            this._text('Sidetone: aktueller Pegel unbekannt', 'Sidetone: current level unknown'),
            {reactive: false, can_focus: false});
        this._indicator.menu.addMenuItem(this._sidetoneStatus);
        const sidetoneRow = new PopupMenu.PopupBaseMenuItem({activate: false});
        this._sidetoneSlider = new Slider.Slider(0);
        for (let i = 0; i <= 6; i++)
            this._sidetoneSlider.addMark(i / 6);
        sidetoneRow.add_child(this._sidetoneSlider);
        this._indicator.menu.addMenuItem(sidetoneRow);
        this._sidetoneController = new SidetoneController({
            apply: level => this._applySidetone(level),
            showSelection: level => {
                this._sidetoneStatus.label.text = `Sidetone: ${sidetonePercent(level)}%`;
            },
            showResult: level => {
                this._sidetoneStatus.label.text =
                    `${this._text('Sidetone zuletzt gesetzt', 'Sidetone last set')}: ${sidetonePercent(level)}%`;
            },
            showError: error => {
                this._sidetoneStatus.label.text =
                    this._text('Sidetone-Fehler – siehe Protokoll', 'Sidetone error – see log');
                console.error(`Astro A50 sidetone: ${error}`);
            },
            schedule: callback => GLib.timeout_add(GLib.PRIORITY_DEFAULT, 350, () => {
                callback();
                return GLib.SOURCE_REMOVE;
            }),
            cancel: id => GLib.source_remove(id),
        });
        this._sidetoneSlider.connect('drag-begin', () => this._sidetoneController.beginDrag());
        this._sidetoneSlider.connect('drag-end', () => this._sidetoneController.endDrag());
        this._sidetoneSlider.connect('notify::value', () =>
            this._sidetoneController.change(sidetoneLevel(this._sidetoneSlider.value)));
        const equalizerMenu = new PopupMenu.PopupSubMenuMenuItem(
            this._text('Equalizer-Presets', 'Equalizer presets'));
        this._eqStatus = new PopupMenu.PopupMenuItem(
            this._text('EQ: unbekannt', 'EQ: unknown'),
            {reactive: false, can_focus: false});
        equalizerMenu.menu.addMenuItem(this._eqStatus);
        this._eqPresetItems = [];
        for (const preset of EQ_PRESETS) {
            const item = new PopupMenu.PopupMenuItem(preset);
            item.connect('activate', () => this._applyEqualizerPreset(preset));
            equalizerMenu.menu.addMenuItem(item);
            this._eqPresetItems.push(item);
        }
        this._indicator.menu.addMenuItem(equalizerMenu);
        this._bluetoothStatus = new PopupMenu.PopupMenuItem(
            this._text('Bluetooth: wird geprüft', 'Bluetooth: checking'),
            {reactive: false, can_focus: false});
        this._indicator.menu.addMenuItem(this._bluetoothStatus);
        const refresh = new PopupMenu.PopupMenuItem(this._text('Aktualisieren', 'Refresh'));
        refresh.connect('activate', () => this._refresh());
        this._indicator.menu.addMenuItem(refresh);
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        this._refresh();
        this._refreshMicrophone();
        this._refreshBluetooth();
        this._timer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            });
        this._micTimer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, MICROPHONE_POLL_SECONDS, () => {
                this._refreshMicrophone();
                return GLib.SOURCE_CONTINUE;
            });
        this._bluetoothTimer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, 15, () => {
                this._refreshBluetooth();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _text(german, english) {
        return this._german ? german : english;
    }

    async _refreshBluetooth() {
        if (this._disposed || this._bluetoothBusy)
            return;
        const command = GLib.build_filenamev([
            GLib.get_home_dir(),
            '.local',
            'bin',
            'a50-base-station',
        ]);
        this._bluetoothBusy = true;
        try {
            const output = await this._runCommand([command, 'bluetooth']);
            const status = JSON.parse(output);
            if (
                !status
                || typeof status.connected !== 'boolean'
                || (status.device_name !== null && typeof status.device_name !== 'string')
                || (!status.connected && status.device_name !== null)
            )
                throw new Error('Invalid Bluetooth status');
            if (!this._disposed) {
                this._bluetoothStatus.label.text = status.connected
                    ? `Bluetooth: ${this._text('verbunden', 'connected')} · ${status.device_name || this._text('Gerät', 'device')}`
                    : `Bluetooth: ${this._text('kein Gerät verbunden', 'no device connected')}`;
            }
            this._lastBluetoothError = null;
        } catch (error) {
            if (!this._disposed) {
                this._bluetoothStatus.label.text =
                    this._text('Bluetooth: nicht verfügbar', 'Bluetooth: unavailable');
                const message = String(error);
                if (message !== this._lastBluetoothError)
                    console.error(`Astro A50 Bluetooth: ${message}`);
                this._lastBluetoothError = message;
            }
        } finally {
            this._bluetoothBusy = false;
        }
    }

    async _applySidetone(level) {
        const command = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'a50-sidetone']);
        await this._runCommand([command, String(level)]);
    }

    async _applyEqualizerPreset(preset) {
        if (this._disposed || this._eqBusy)
            return;
        const command = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'a50-equalizer']);
        this._eqBusy = true;
        for (const item of this._eqPresetItems)
            item.setSensitive(false);
        try {
            await this._runCommand([command, 'apply', preset]);
            if (!this._disposed)
                this._eqStatus.label.text =
                    `${this._text('EQ zuletzt gesetzt', 'EQ last set')}: ${preset}`;
        } catch (error) {
            if (!this._disposed) {
                this._eqStatus.label.text =
                    this._text('EQ-Fehler – siehe Protokoll', 'EQ error – see log');
                console.error(`Astro A50 equalizer: ${error}`);
            }
        } finally {
            this._eqBusy = false;
            if (!this._disposed) {
                for (const item of this._eqPresetItems)
                    item.setSensitive(true);
            }
        }
    }

    _refresh() {
        if (this._disposed || this._process)
            return;

        try {
            const command = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'a50-battery']);
            this._process = Gio.Subprocess.new(
                [command, '--json'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            this._cancellable = new Gio.Cancellable();
            this._process.communicate_utf8_async(null, this._cancellable, (process, result) => {
                if (this._disposed)
                    return;
                try {
                    const [, stdout, stderr] = process.communicate_utf8_finish(result);
                    if (!process.get_successful())
                        throw new Error(stderr.trim() || `Exit status ${process.get_exit_status()}`);
                    const status = parseStatus(stdout);
                    this._icon.icon_name = batteryIcon(status.level, status.charging);
                    const color = batteryColor(status.level, status.charging);
                    this._icon.set_style(color ? `color: ${color};` : null);
                    this._label.text = `A50 ${status.level}%`;
                    const charging = status.charging
                        ? this._text('lädt', 'charging')
                        : this._text('lädt nicht', 'not charging');
                    this._details.label.text = `${status.level}% · ${charging} · ${this._text('experimentell', 'experimental')}`;
                    this._lastError = null;
                } catch (error) {
                    this._showError(error);
                } finally {
                    this._process = null;
                    this._cancellable = null;
                }
            });
        } catch (error) {
            this._process = null;
            this._cancellable = null;
            this._showError(error);
        }
    }

    _showError(error) {
        this._icon.icon_name = 'battery-missing-symbolic';
        this._icon.set_style(null);
        this._label.text = 'A50 ?';
        this._details.label.text = this._text('Akku nicht verfügbar', 'Battery unavailable');
        const message = String(error);
        if (message !== this._lastError)
            console.error(`Astro A50 battery: ${message}`);
        this._lastError = message;
    }

    _refreshMicrophone() {
        if (this._disposed || this._micProcess || this._micBusy)
            return;

        try {
            this._micProcess = Gio.Subprocess.new(
                ['/usr/bin/pw-dump'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            this._micCancellable = new Gio.Cancellable();
            this._micProcess.communicate_utf8_async(
                null, this._micCancellable, (process, result) => {
                    if (this._disposed)
                        return;
                    try {
                        const [, stdout, stderr] = process.communicate_utf8_finish(result);
                        if (!process.get_successful())
                            throw new Error(stderr.trim() || `Exit status ${process.get_exit_status()}`);
                        const status = parseMicrophoneStatus(stdout);
                        this._showMicrophone(status.state);
                        this._lastMicError = null;
                    } catch (error) {
                        this._showMicrophoneError(error);
                    } finally {
                        this._micProcess = null;
                        this._micCancellable = null;
                    }
                });
        } catch (error) {
            this._micProcess = null;
            this._micCancellable = null;
            this._showMicrophoneError(error);
        }
    }

    _showMicrophone(state) {
        const muted = state === 'muted'
            ? this._text('stumm', 'muted')
            : state === 'unmuted'
                ? this._text('aktiv', 'on')
                : this._text('unterschiedliche Zustände', 'mixed states');
        this._micIcon.icon_name = microphoneIcon(state);
        this._micToggleItem.label.text = `${this._text('Mikrofon', 'Microphone')}: ${muted}`;
        this._micToggleItem.setSensitive(true);
    }

    _showMicrophoneError(error) {
        this._micIcon.icon_name = 'audio-input-microphone-symbolic';
        this._micToggleItem.label.text = this._text(
            'Mikrofon nicht verfügbar',
            'Microphone unavailable');
        this._micToggleItem.setSensitive(false);
        const message = String(error);
        if (message !== this._lastMicError)
            console.error(`Astro A50 microphone: ${message}`);
        this._lastMicError = message;
    }

    async _runCommand(argv) {
        const process = Gio.Subprocess.new(
            argv,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        const [, stdout, stderr] = await new Promise((resolve, reject) => {
            process.communicate_utf8_async(null, null, (subprocess, result) => {
                try {
                    resolve(subprocess.communicate_utf8_finish(result));
                } catch (error) {
                    reject(error);
                }
            });
        });
        if (!process.get_successful())
            throw new Error(stderr.trim() || `Command failed: ${argv[0]}`);
        return stdout;
    }

    async _toggleMicrophone() {
        if (this._disposed || this._micBusy)
            return;
        this._micBusy = true;
        this._micToggleItem.setSensitive(false);
        try {
            const output = await this._runCommand(['/usr/bin/pw-dump']);
            const status = parseMicrophoneStatus(output);
            const muted = toggledMicrophoneMute(status.state);
            const value = muted ? '1' : '0';
            for (const source of Object.values(status.sources))
                await this._runCommand(['/usr/bin/wpctl', 'set-mute', String(source.id), value]);
            const sound = GLib.build_filenamev([
                GLib.get_home_dir(),
                '.local/share/toggle-mic-mute-sounds',
                muted ? 'mute.wav' : 'unmute.wav',
            ]);
            await this._runCommand(['/usr/bin/paplay', '--volume=65536', sound]);
            this._showMicrophone(muted ? 'muted' : 'unmuted');
        } catch (error) {
            this._showMicrophoneError(error);
        } finally {
            this._micBusy = false;
            this._refreshMicrophone();
        }
    }

    disable() {
        this._disposed = true;
        this._sidetoneController.dispose();
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        if (this._micTimer) {
            GLib.source_remove(this._micTimer);
            this._micTimer = null;
        }
        if (this._bluetoothTimer) {
            GLib.source_remove(this._bluetoothTimer);
            this._bluetoothTimer = null;
        }
        if (this._cancellable)
            this._cancellable.cancel();
        if (this._process)
            this._process.force_exit();
        if (this._micCancellable)
            this._micCancellable.cancel();
        if (this._micProcess)
            this._micProcess.force_exit();
        this._process = null;
        this._micProcess = null;
        this._cancellable = null;
        this._micCancellable = null;
        this._indicator.destroy();
        this._indicator = null;
    }
}
