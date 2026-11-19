#!/usr/bin/python3
import json
import math
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk


SOURCE_NAMES = {
    "alsa_input.usb-Logitech_A50-00.pro-input-0",
    "alsa_input.usb-Logitech_A50-00.pro-input-1",
}
SOUND_DIR = Path.home() / ".local/share/toggle-mic-mute-sounds"
BATTERY_COMMAND = Path.home() / ".local/bin/a50-battery"
SIDETONE_COMMAND = Path.home() / ".local/bin/a50-sidetone"
EQUALIZER_COMMAND = Path.home() / ".local/bin/a50-equalizer"
MICROPHONE_EQ_COMMAND = Path.home() / ".local/bin/a50-microphone-equalizer"
MICROPHONE_NOISE_GATE_COMMAND = Path.home() / ".local/bin/a50-microphone-noise-gate"
BASE_STATION_COMMAND = Path.home() / ".local/bin/a50-base-station"
DEVICE_STATUS_COMMAND = Path.home() / ".local/bin/a50-device-status"
FACTORY_EQ_PRESETS = ("Standard",)
EQUALIZER_BANDS = (
    "20 Hz",
    "50 Hz",
    "125 Hz",
    "250 Hz",
    "500 Hz",
    "1 kHz",
    "2.5 kHz",
    "5 kHz",
    "10 kHz",
    "20 kHz",
)
MICROPHONE_EQ_BANDS = (
    "80 Hz",
    "150 Hz",
    "250 Hz",
    "400 Hz",
    "800 Hz",
    "1.5 kHz",
    "2.5 kHz",
    "5 kHz",
    "10 kHz",
    "19 kHz",
)
FACTORY_MICROPHONE_EQ_PRESETS = ("Standard",)
MICROPHONE_NOISE_GATE_STATES = ("Aus", "Nacht", "Zu Hause", "Turnier")
MICROPHONE_NOISE_GATE_IDS = {"Aus": 0, "Nacht": 2, "Zu Hause": 1, "Turnier": 4}
SLEEP_TIMEOUTS = {"Aus": "off", "15 Minuten": "15", "30 Minuten": "30", "60 Minuten": "60"}
SOUND_MODES = {"Alle": "all", "Minimal": "minimal", "Aus": "off"}
AUTO_APPLY_DELAY_MS = 350
AUTO_APPLY_KEYS = frozenset({
    "sidetone", "brightness", "sleep", "sound", "equalizer",
    "microphone_equalizer", "microphone_noise_gate",
})
READ_SETTINGS = (
    "sidetone", "brightness", "sleep", "sound", "noise-gate",
    "output-eq", "microphone-eq",
)
HID_WORK_KEYS = AUTO_APPLY_KEYS | {"battery", "bluetooth"} | {
    f"read-{setting}" for setting in READ_SETTINGS
}
SAVE_KEYS = frozenset({"equalizer_save", "microphone_equalizer_save"})


def read_microphone_states() -> dict[str, tuple[int, bool]]:
    result = subprocess.run(
        ["pw-dump"], check=True, capture_output=True, text=True, timeout=5
    )
    nodes = json.loads(result.stdout)
    sources = {}
    for node in nodes:
        info = node.get("info", {})
        props = info.get("props", {})
        name = props.get("node.name")
        if name not in SOURCE_NAMES or props.get("media.class") != "Audio/Source":
            continue
        mute = next(
            (
                item["mute"]
                for item in info.get("params", {}).get("Props", [])
                if isinstance(item, dict) and isinstance(item.get("mute"), bool)
            ),
            None,
        )
        if mute is None:
            raise RuntimeError(f"Could not read mute state for {name}")
        sources[name] = (node["id"], mute)
    if sources.keys() != SOURCE_NAMES:
        raise RuntimeError("Both A50 microphone sources are not available")
    return sources


def microphone_state(sources: dict[str, tuple[int, bool]]) -> str:
    muted = {state for _, state in sources.values()}
    if muted == {True}:
        return "muted"
    if muted == {False}:
        return "unmuted"
    return "mixed"


def toggled_mute_state(sources: dict[str, tuple[int, bool]]) -> bool:
    return microphone_state(sources) != "muted"


def toggle_microphones() -> bool:
    sources = read_microphone_states()
    target_muted = toggled_mute_state(sources)
    for source_id, _ in sources.values():
        subprocess.run(
            ["wpctl", "set-mute", str(source_id), "1" if target_muted else "0"],
            check=True,
            timeout=5,
        )
    sound = SOUND_DIR / ("mute.wav" if target_muted else "unmute.wav")
    subprocess.run(
        ["paplay", "--volume=65536", str(sound)], check=True, timeout=5
    )
    return target_muted


def read_battery() -> dict:
    result = subprocess.run(
        [str(BATTERY_COMMAND), "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    status = json.loads(result.stdout)
    level = status.get("level")
    if (
        not isinstance(level, int)
        or isinstance(level, bool)
        or not 0 <= level <= 100
        or not isinstance(status.get("charging"), bool)
        or status.get("experimental") is not True
    ):
        raise ValueError("Invalid A50 battery status")
    return status


def battery_icon(level: int, charging: bool) -> str:
    rounded = level // 10 * 10
    suffix = "-charged" if charging and rounded == 100 else "-charging" if charging else ""
    return f"battery-level-{rounded}{suffix}-symbolic"


BATTERY_COLOR_CLASSES = ("a50-battery-charging", "a50-battery-full", "a50-battery-low", "a50-battery-medium")
BATTERY_CSS = b"""
.a50-battery-charging { color: #33d17a; }
.a50-battery-full { color: #26a269; }
.a50-battery-low { color: #e01b24; }
.a50-battery-medium { color: #e5a50a; }
"""


def battery_color_class(level: int, charging: bool):
    if charging:
        return "a50-battery-full" if level == 100 else "a50-battery-charging"
    if level <= 20:
        return "a50-battery-low"
    if level <= 40:
        return "a50-battery-medium"
    return None


def set_sidetone(level: int) -> None:
    result = subprocess.run(
        [str(SIDETONE_COMMAND), str(level)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Sidetone command failed: {result.returncode}")


def read_microphone_noise_gate_states() -> tuple[str, ...]:
    result = subprocess.run(
        [str(MICROPHONE_NOISE_GATE_COMMAND), "list"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    states = json.loads(result.stdout)
    if not isinstance(states, dict) or states != MICROPHONE_NOISE_GATE_IDS:
        raise ValueError("Invalid microphone noise-gate states")
    return tuple(states)


def set_microphone_noise_gate(state: str) -> None:
    result = subprocess.run(
        [str(MICROPHONE_NOISE_GATE_COMMAND), "set", state],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Microphone noise-gate command failed: {result.returncode}"
        )


def set_base_station_brightness(level: int) -> None:
    result = subprocess.run(
        [str(BASE_STATION_COMMAND), "brightness", str(level)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Base-station brightness command failed: {result.returncode}"
        )


def set_sleep_timeout(label: str) -> None:
    try:
        value = SLEEP_TIMEOUTS[label]
    except KeyError as error:
        raise ValueError(f"Unknown A50 sleep timeout: {label!r}") from error
    result = subprocess.run(
        [str(BASE_STATION_COMMAND), "sleep", value],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Sleep-timeout command failed: {result.returncode}"
        )


def set_headset_sound_mode(label: str) -> None:
    try:
        value = SOUND_MODES[label]
    except KeyError as error:
        raise ValueError(f"Unknown A50 sound mode: {label!r}") from error
    result = subprocess.run(
        [str(BASE_STATION_COMMAND), "sound", value],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Sound-mode command failed: {result.returncode}"
        )


def read_bluetooth_status() -> dict[str, bool | str | None]:
    result = subprocess.run(
        [str(BASE_STATION_COMMAND), "bluetooth"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    status = json.loads(result.stdout)
    if (
        not isinstance(status, dict)
        or type(status.get("connected")) is not bool
        or (
            status.get("device_name") is not None
            and not isinstance(status.get("device_name"), str)
        )
        or (not status["connected"] and status["device_name"] is not None)
    ):
        raise ValueError("Invalid A50 Bluetooth status")
    return status


def read_device_setting(setting: str) -> int | list[float]:
    result = subprocess.run(
        [str(DEVICE_STATUS_COMMAND), setting],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Status command failed: {result.returncode}")
    value = json.loads(result.stdout)
    if setting in ("output-eq", "microphone-eq"):
        if (
            not isinstance(value, list)
            or len(value) != 10
            or any(
                type(gain) not in (int, float)
                or not math.isfinite(gain)
                or not -6 <= gain <= 6
                or not math.isclose(gain * 2, round(gain * 2), abs_tol=1e-9)
                for gain in value
            )
        ):
            raise ValueError(f"Invalid {setting} readback")
    elif (
        type(value) is not int
        or setting not in ("sidetone", "brightness", "sleep", "sound", "noise-gate")
        or (setting == "sidetone" and not 0 <= value <= 6)
        or (setting == "brightness" and not 0 <= value <= 100)
        or (setting == "sleep" and value not in (0, 15, 30, 60))
        or (setting == "sound" and value not in (0, 1, 2))
        or (setting == "noise-gate" and value not in (0, 1, 2, 4))
    ):
        raise ValueError(f"Invalid {setting} readback")
    return value


def read_equalizer_presets() -> dict[str, list[int | float]]:
    result = subprocess.run(
        [str(EQUALIZER_COMMAND), "list"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    presets = json.loads(result.stdout)
    if not isinstance(presets, dict) or not presets:
        raise ValueError("Invalid EQ preset list")
    for name, gains in presets.items():
        if (
            not isinstance(name, str)
            or not isinstance(gains, list)
            or len(gains) != len(EQUALIZER_BANDS)
            or any(
                type(gain) not in (int, float)
                or not -6 <= gain <= 6
                or not math.isfinite(gain)
                or not math.isclose(gain * 2, round(gain * 2), abs_tol=1e-9)
                for gain in gains
            )
        ):
            raise ValueError("Invalid EQ preset data")
    return presets


def apply_equalizer(gains: list[int | float], preset_name: str | None = None) -> None:
    command = (
        [str(EQUALIZER_COMMAND), "apply", preset_name]
        if preset_name is not None
        else [str(EQUALIZER_COMMAND), "apply-values", *map(str, gains)]
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"EQ command failed: {result.returncode}")


def save_equalizer_preset(
    name: str, gains: list[int | float]
) -> dict[str, list[int | float]]:
    result = subprocess.run(
        [str(EQUALIZER_COMMAND), "save", name, *map(str, gains)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"EQ save failed: {result.returncode}")
    return read_equalizer_presets()


def read_microphone_equalizer_presets() -> dict[str, list[int | float]]:
    result = subprocess.run(
        [str(MICROPHONE_EQ_COMMAND), "list"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    presets = json.loads(result.stdout)
    if not isinstance(presets, dict) or not presets:
        raise ValueError("Invalid microphone EQ preset list")
    for name, gains in presets.items():
        if (
            not isinstance(name, str)
            or not isinstance(gains, list)
            or len(gains) != len(MICROPHONE_EQ_BANDS)
            or any(
                type(gain) not in (int, float)
                or not math.isfinite(gain)
                or not -6 <= gain <= 6
                or not math.isclose(gain * 2, round(gain * 2), abs_tol=1e-9)
                for gain in gains
            )
        ):
            raise ValueError("Invalid microphone EQ preset data")
    return presets


def apply_microphone_equalizer(
    gains: list[int | float], preset_name: str | None = None
) -> None:
    command = (
        [str(MICROPHONE_EQ_COMMAND), "apply", preset_name]
        if preset_name is not None
        else [
            str(MICROPHONE_EQ_COMMAND),
            "apply-values",
            *map(str, gains),
        ]
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Microphone EQ command failed: {result.returncode}"
        )


def save_microphone_equalizer_preset(
    name: str, gains: list[int | float]
) -> dict[str, list[int | float]]:
    result = subprocess.run(
        [
            str(MICROPHONE_EQ_COMMAND),
            "save",
            name,
            *map(str, gains),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"Microphone EQ save failed: {result.returncode}"
        )
    return read_microphone_equalizer_presets()


class A50ControlWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Astro A50")
        self.set_default_size(900, 780)
        self._german = any(
            language.startswith("de") for language in GLib.get_language_names()
        )
        self._disposed = False
        self._closing = False
        self._allow_close = False
        self._hid_lock = threading.Lock()
        self._busy = {
            "battery": False,
            "microphone": False,
            "sidetone": False,
            "equalizer": False,
            "equalizer_save": False,
            "microphone_equalizer": False,
            "microphone_equalizer_save": False,
            "microphone_noise_gate": False,
            "brightness": False,
            "sleep": False,
            "sound": False,
            "bluetooth": False,
            **{f"read-{setting}": False for setting in READ_SETTINGS},
        }
        self._loading_status = False
        self._eq_read_ready = False
        self._mic_eq_read_ready = False
        self._eq_read_error = None
        self._mic_eq_read_error = None
        self._eq_selection_initialized = False
        self._mic_eq_selection_initialized = False
        self._eq_preset_error = None
        self._mic_eq_preset_error = None
        self._noise_gate_read_ready = False
        self._noise_gate_list_ready = False
        self._noise_gate_initial_id = None
        self._noise_gate_read_error = None
        self._auto_pending = {}
        self._auto_timers = {}
        self._mic_state = None
        self.connect("close-request", self._on_close_request)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="Astro A50", subtitle=self._text("Linux-Steuerung", "Linux controls"))
        )
        header.pack_start(self._build_battery_status())
        header.pack_end(self._build_microphone_button())
        toolbar.add_top_bar(header)
        self._pages = Gtk.Stack(hexpand=True, vexpand=True)
        for name, title, content in (
            ("settings", self._text("Einstellungen", "Settings"), self._build_hero()),
            ("output-eq", self._text("EQ Ausgabe", "Output EQ"), self._build_equalizer_controls()),
            ("microphone-eq", self._text("EQ Mikrofon", "Microphone EQ"), self._build_microphone_equalizer_controls()),
        ):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_margin_top(24)
            scroll.set_margin_bottom(24)
            scroll.set_margin_start(16)
            scroll.set_margin_end(16)
            scroll.set_child(content)
            self._pages.add_titled(scroll, name, title)
        self._pages.set_visible_child_name("settings")
        sidebar = Gtk.StackSidebar(stack=self._pages)
        sidebar.set_size_request(170, -1)
        layout = Gtk.Box()
        layout.append(sidebar)
        layout.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        layout.append(self._pages)
        toolbar.set_content(layout)
        self.set_content(toolbar)

        self._refresh_battery()
        self._refresh_microphone()
        self._battery_timer = GLib.timeout_add_seconds(
            60, self._refresh_battery_timer
        )
        self._microphone_timer = GLib.timeout_add_seconds(
            2, self._refresh_microphone_timer
        )
        self._refresh_equalizer_presets()
        self._refresh_microphone_equalizer_presets()
        self._refresh_microphone_noise_gate_states()
        self._refresh_bluetooth()
        self._refresh_device_settings()
        self._bluetooth_timer = GLib.timeout_add_seconds(
            15, self._refresh_bluetooth_timer
        )

    def _text(self, german, english):
        return german if self._german else english

    def _build_battery_status(self):
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self._battery_icon = Gtk.Image.new_from_icon_name("battery-missing-symbolic")
        self._battery_icon.set_pixel_size(24)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._battery_percent = Gtk.Label(label="A50 --%")
        self._battery_percent.add_css_class("heading")
        self._battery_state = Gtk.Label(label=self._text("Akku", "Battery"))
        self._battery_state.add_css_class("dim-label")
        labels.append(self._battery_percent)
        labels.append(self._battery_state)
        box.append(self._battery_icon)
        box.append(labels)
        return box

    def _build_microphone_button(self):
        self._mic_button = Gtk.Button()
        self._mic_button.add_css_class("flat")
        self._mic_button.connect("clicked", self._on_microphone_clicked)
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self._mic_icon = Gtk.Image.new_from_icon_name(
            "audio-input-microphone-symbolic"
        )
        self._mic_icon.set_pixel_size(24)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._mic_label = Gtk.Label(label=self._text("Mikrofon", "Microphone"))
        self._mic_label.add_css_class("heading")
        self._mic_state_label = Gtk.Label(
            label=self._text("Wird geprüft", "Checking")
        )
        self._mic_state_label.add_css_class("dim-label")
        labels.append(self._mic_label)
        labels.append(self._mic_state_label)
        box.append(self._mic_icon)
        box.append(labels)
        self._mic_button.set_child(box)
        self._mic_button.set_tooltip_text(
            self._text(
                "Beide A50-Mikrofone stummschalten oder aktivieren",
                "Mute or unmute both A50 microphones",
            )
        )
        return self._mic_button

    def _build_hero(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            vexpand=True,
        )
        self._headset_icon = Gtk.Image.new_from_icon_name(
            "audio-headphones-symbolic"
        )
        self._headset_icon.set_pixel_size(112)
        self._headset_icon.add_css_class("dim-label")
        name = Gtk.Label(label="ASTRO A50")
        name.add_css_class("title-1")
        caption = Gtk.Label(
            label=self._text("Game · Voice", "Game · Voice")
        )
        caption.add_css_class("dim-label")
        box.append(self._headset_icon)
        box.append(name)
        box.append(caption)
        sidetone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidetone.set_size_request(300, -1)
        self._sidetone_label = Gtk.Label(label="Sidetone: 0%")
        self._sidetone_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 6, 1)
        self._sidetone_scale.set_draw_value(False)
        self._sidetone_scale.set_round_digits(0)
        self._sidetone_scale.set_sensitive(False)
        self._sidetone_scale.connect("value-changed", self._on_sidetone_changed)
        self._sidetone_status = Gtk.Label(
            label=self._text("Aktueller Pegel unbekannt", "Current level unknown")
        )
        self._sidetone_status.add_css_class("dim-label")
        sidetone.append(self._sidetone_label)
        sidetone.append(self._sidetone_scale)
        sidetone.append(self._sidetone_status)
        box.append(sidetone)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._build_base_station_controls())
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self._build_microphone_noise_gate_controls())
        return box

    def _build_microphone_noise_gate_controls(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        box.set_size_request(520, -1)
        title = Gtk.Label(
            label=self._text("Mikrofon-Noise-Gate", "Microphone noise gate")
        )
        title.add_css_class("title-2")
        box.append(title)
        self._noise_gate_combo = Gtk.ComboBoxText()
        self._noise_gate_combo.set_sensitive(False)
        self._noise_gate_combo.connect(
            "changed", self._on_microphone_noise_gate_changed
        )
        box.append(self._noise_gate_combo)
        self._noise_gate_status = Gtk.Label(
            label=self._text(
                "Aktueller Noise-Gate-Zustand unbekannt",
                "Current noise-gate state unknown",
            )
        )
        self._noise_gate_status.add_css_class("dim-label")
        box.append(self._noise_gate_status)
        return box

    def _build_base_station_controls(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        box.set_size_request(520, -1)
        title = Gtk.Label(label=self._text("Basisstation", "Base station"))
        title.add_css_class("title-2")
        box.append(title)

        brightness_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        brightness_label = Gtk.Label(
            label=self._text("Helligkeit", "Brightness")
        )
        brightness_label.set_size_request(100, -1)
        self._brightness_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self._brightness_scale.set_value(100)
        self._brightness_scale.set_draw_value(False)
        self._brightness_scale.set_hexpand(True)
        self._brightness_scale.set_sensitive(False)
        self._brightness_value = Gtk.Label(label="100%")
        self._brightness_value.set_size_request(44, -1)
        self._brightness_scale.connect(
            "value-changed", self._on_brightness_changed
        )
        brightness_row.append(brightness_label)
        brightness_row.append(self._brightness_scale)
        brightness_row.append(self._brightness_value)
        box.append(brightness_row)
        self._brightness_status = Gtk.Label(
            label=self._text(
                "Aktueller Wert unbekannt",
                "Current value unknown",
            )
        )
        self._brightness_status.add_css_class("dim-label")
        box.append(self._brightness_status)

        sleep_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        sleep_label = Gtk.Label(label=self._text("Ruhezustand", "Sleep timeout"))
        sleep_label.set_size_request(100, -1)
        self._sleep_combo = Gtk.ComboBoxText()
        self._sleep_combo.set_hexpand(True)
        self._sleep_combo.set_sensitive(False)
        for option in SLEEP_TIMEOUTS:
            self._sleep_combo.append_text(option)
        self._sleep_combo.connect("changed", self._on_sleep_timeout_changed)
        sleep_row.append(sleep_label)
        sleep_row.append(self._sleep_combo)
        box.append(sleep_row)
        self._sleep_status = Gtk.Label(
            label=self._text("Aktueller Wert unbekannt", "Current value unknown")
        )
        self._sleep_status.add_css_class("dim-label")
        box.append(self._sleep_status)

        sound_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        sound_label = Gtk.Label(label=self._text("Töne", "Sounds"))
        sound_label.set_size_request(100, -1)
        self._sound_combo = Gtk.ComboBoxText()
        self._sound_combo.set_hexpand(True)
        self._sound_combo.set_sensitive(False)
        for option in SOUND_MODES:
            self._sound_combo.append_text(option)
        self._sound_combo.connect("changed", self._on_sound_mode_changed)
        sound_row.append(sound_label)
        sound_row.append(self._sound_combo)
        box.append(sound_row)
        self._sound_status = Gtk.Label(
            label=self._text("Aktueller Wert unbekannt", "Current value unknown")
        )
        self._sound_status.add_css_class("dim-label")
        box.append(self._sound_status)

        bluetooth_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        bluetooth_label = Gtk.Label(label="Bluetooth")
        bluetooth_label.set_size_request(100, -1)
        self._bluetooth_status = Gtk.Label(
            label=self._text("Wird geprüft", "Checking")
        )
        self._bluetooth_status.set_hexpand(True)
        self._bluetooth_status.set_xalign(0)
        self._bluetooth_refresh_button = Gtk.Button(
            label=self._text("Aktualisieren", "Refresh")
        )
        self._bluetooth_refresh_button.connect(
            "clicked", self._on_bluetooth_refresh_clicked
        )
        bluetooth_row.append(bluetooth_label)
        bluetooth_row.append(self._bluetooth_status)
        bluetooth_row.append(self._bluetooth_refresh_button)
        box.append(bluetooth_row)
        return box

    def _on_brightness_changed(self, scale):
        level = round(scale.get_value())
        self._brightness_value.set_text(f"{level}%")
        if self._loading_status:
            return
        self._run_base_station_setting(
            "brightness", self._brightness_status,
            lambda: set_base_station_brightness(level), f"{level}%",
        )

    def _run_base_station_setting(self, key, status_label, function, value):
        self._queue_auto_apply(
            key,
            function,
            lambda _result, error: self._show_base_station_setting(
                status_label, value, error
            ),
            status_label,
        )

    def _show_base_station_setting(self, status_label, value, error):
        if error:
            status_label.set_text(
                self._text("Befehl fehlgeschlagen", "Command failed")
            )
            status_label.set_tooltip_text(error)
            return
        status_label.set_text(
            self._text(
                f"Befehl bestätigt: {value}",
                f"Command acknowledged: {value}",
            )
        )
        status_label.set_tooltip_text(
            self._text(
                "Die Bestätigung liest den Wert nicht erneut aus",
                "The acknowledgement does not read the value back",
            )
        )

    def _on_sleep_timeout_changed(self, combo):
        if self._loading_status:
            return
        label = combo.get_active_text()
        if label not in SLEEP_TIMEOUTS:
            return
        self._run_base_station_setting(
            "sleep",
            self._sleep_status,
            lambda: set_sleep_timeout(label),
            label,
        )

    def _on_sound_mode_changed(self, combo):
        if self._loading_status:
            return
        label = combo.get_active_text()
        if label not in SOUND_MODES:
            return
        self._run_base_station_setting(
            "sound",
            self._sound_status,
            lambda: set_headset_sound_mode(label),
            label,
        )

    def _on_bluetooth_refresh_clicked(self, _button):
        self._refresh_bluetooth()

    def _refresh_bluetooth(self):
        if self._disposed or self._busy["bluetooth"]:
            return GLib.SOURCE_REMOVE
        self._bluetooth_refresh_button.set_sensitive(False)
        self._run_in_background(
            "bluetooth",
            read_bluetooth_status,
            self._show_bluetooth_status,
        )
        return GLib.SOURCE_REMOVE

    def _refresh_bluetooth_timer(self):
        self._refresh_bluetooth()
        return GLib.SOURCE_CONTINUE

    def _show_bluetooth_status(self, status, error):
        self._bluetooth_refresh_button.set_sensitive(True)
        if error:
            self._bluetooth_status.set_text(
                self._text("Bluetooth nicht verfügbar", "Bluetooth unavailable")
            )
            self._bluetooth_status.set_tooltip_text(error)
            return
        if status["connected"]:
            name = status["device_name"] or self._text("Verbunden", "Connected")
            text = self._text(f"Verbunden: {name}", f"Connected: {name}")
        else:
            text = self._text("Kein Gerät verbunden", "No device connected")
        self._bluetooth_status.set_text(text)
        self._bluetooth_status.set_tooltip_text(
            self._text(
                "Bluetooth-Status wird angezeigt, nicht gesteuert",
                "Bluetooth status is displayed, not controlled",
            )
        )

    def _refresh_microphone_noise_gate_states(self):
        self._run_in_background(
            "microphone_noise_gate",
            read_microphone_noise_gate_states,
            self._show_microphone_noise_gate_states,
        )

    def _show_microphone_noise_gate_states(self, states, error):
        if error:
            self._noise_gate_status.set_text(
                self._text(
                    "Noise-Gate-Stufen nicht verfügbar",
                    "Noise-gate states unavailable",
                )
            )
            self._noise_gate_status.set_tooltip_text(error)
            self._noise_gate_combo.set_sensitive(False)
            return
        self._noise_gate_combo.remove_all()
        for state in states:
            self._noise_gate_combo.append_text(state)
        self._noise_gate_list_ready = True
        self._finish_initial_noise_gate()

    def _on_microphone_noise_gate_changed(self, combo):
        if self._loading_status:
            return
        state = combo.get_active_text()
        if state not in MICROPHONE_NOISE_GATE_STATES:
            return
        self._queue_auto_apply(
            "microphone_noise_gate",
            lambda: (set_microphone_noise_gate(state), state)[1],
            self._show_microphone_noise_gate_result,
            self._noise_gate_status,
        )

    def _show_microphone_noise_gate_result(self, state, error):
        if error:
            self._noise_gate_status.set_text(
                self._text("Noise-Gate-Fehler", "Noise-gate error")
            )
            self._noise_gate_status.set_tooltip_text(error)
            return
        self._noise_gate_status.set_text(
            self._text(
                f"Befehl bestätigt: {state}",
                f"Command acknowledged: {state}",
            )
        )
        self._noise_gate_status.set_tooltip_text(
            self._text(
                "Die Gerätebestätigung liest den aktiven Zustand nicht zurück",
                "The device acknowledgement does not read back the active state",
            )
        )

    def _build_equalizer_controls(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        box.set_size_request(520, -1)
        self._eq_loading = False
        self._eq_presets = {}
        title = Gtk.Label(label=self._text("Ausgabe-Equalizer", "Output equalizer"))
        title.add_css_class("title-2")
        box.append(title)
        self._eq_combo = Gtk.ComboBoxText()
        self._eq_combo.set_sensitive(False)
        self._eq_combo.connect("changed", self._on_equalizer_preset_changed)
        box.append(self._eq_combo)
        self._eq_scales = []
        for band in EQUALIZER_BANDS:
            row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            label = Gtk.Label(label=band)
            label.set_size_request(64, -1)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -6, 6, 0.5)
            scale.set_digits(1)
            scale.set_draw_value(False)
            scale.set_value(0)
            scale.set_hexpand(True)
            scale.set_sensitive(False)
            value = Gtk.Label(label="0 dB")
            value.set_size_request(48, -1)
            scale.connect("value-changed", self._on_equalizer_gain_changed, value)
            row.append(label)
            row.append(scale)
            row.append(value)
            box.append(row)
            self._eq_scales.append(scale)

        actions = Gtk.Box(spacing=8)
        self._eq_name_entry = Gtk.Entry()
        self._eq_name_entry.set_placeholder_text(
            self._text("Name für eigenes Preset", "Name for custom preset")
        )
        self._eq_name_entry.set_hexpand(True)
        self._eq_save_button = Gtk.Button(label=self._text("Speichern", "Save"))
        self._eq_save_button.set_sensitive(False)
        self._eq_save_button.connect("clicked", self._on_equalizer_save_clicked)
        actions.append(self._eq_name_entry)
        actions.append(self._eq_save_button)
        box.append(actions)
        self._eq_status = Gtk.Label(
            label=self._text("Aktueller Headset-EQ unbekannt", "Current headset EQ unknown")
        )
        self._eq_status.add_css_class("dim-label")
        box.append(self._eq_status)
        range_note = Gtk.Label(
            label=self._text(
                "Gain-Bereich: −6 bis +6 dB, in 0,5-dB-Schritten",
                "Gain range: −6 to +6 dB, in 0.5 dB steps",
            )
        )
        range_note.add_css_class("dim-label")
        box.append(range_note)
        return box

    def _on_equalizer_gain_changed(self, scale, value_label):
        gain = round(scale.get_value() * 2) / 2
        value_label.set_text(f"{gain:+.1f} dB")
        if self._eq_loading:
            return
        self._mark_equalizer_custom(False)
        self._apply_equalizer()

    def _current_equalizer_gains(self) -> list[float]:
        return [round(scale.get_value() * 2) / 2 for scale in self._eq_scales]

    def _on_equalizer_preset_changed(self, combo):
        if self._eq_loading:
            return
        if not 0 <= combo.get_active() < len(self._eq_presets):
            return
        name = combo.get_active_text()
        if name not in self._eq_presets:
            return
        combo.set_tooltip_text(None)
        self._eq_loading = True
        for scale, gain in zip(self._eq_scales, self._eq_presets[name]):
            scale.set_value(gain)
        self._eq_loading = False
        self._apply_equalizer()

    def _refresh_equalizer_presets(self):
        self._run_in_background(
            "equalizer", read_equalizer_presets, self._show_equalizer_presets
        )

    def _show_equalizer_presets(self, presets, error):
        if error:
            self._eq_preset_error = error
            self._eq_status.set_text(self._text("EQ-Presets nicht verfügbar", "EQ presets unavailable"))
            self._eq_status.set_tooltip_text(error)
            self._eq_save_button.set_sensitive(False)
            return
        self._eq_preset_error = None
        old_count = len(self._eq_presets)
        old_index = self._eq_combo.get_active()
        selected = self._eq_combo.get_active_text()
        self._eq_presets = presets
        self._eq_loading = True
        self._eq_combo.remove_all()
        for name in presets:
            self._eq_combo.append_text(name)
        self._append_equalizer_placeholders(self._eq_combo)
        if 0 <= old_index < old_count and selected in presets:
            self._eq_combo.set_active(list(presets).index(selected))
        elif old_index == old_count:
            self._eq_combo.set_active(len(presets))
        self._eq_loading = False
        self._select_initial_equalizer_preset(False)
        self._eq_combo.set_sensitive(self._eq_read_ready)
        for scale in self._eq_scales:
            scale.set_sensitive(self._eq_read_ready)
        self._eq_save_button.set_sensitive(self._eq_read_ready)

    def _apply_equalizer(self):
        gains = self._current_equalizer_gains()
        name = self._eq_combo.get_active_text()
        factory_preset = (
            name
            if name in FACTORY_EQ_PRESETS
            and gains == self._eq_presets.get(name)
            else None
        )
        self._queue_auto_apply(
            "equalizer",
            lambda: (apply_equalizer(gains, factory_preset), gains)[1],
            self._show_equalizer_applied,
            self._eq_status,
        )

    def _show_equalizer_applied(self, gains, error):
        if error:
            self._eq_status.set_text(self._text("EQ-Fehler", "EQ error"))
            self._eq_status.set_tooltip_text(error)
            return
        self._eq_status.set_text(
            self._text("EQ-Profil angenommen", "EQ profile accepted")
        )
        values = ", ".join(
            f"{band}: {gain:+.1f} dB"
            for band, gain in zip(EQUALIZER_BANDS, gains)
        )
        self._eq_status.set_tooltip_text(
            self._text(
                f"Gesendet: {values}\nDie Bestätigung liest den EQ nicht erneut aus",
                f"Sent: {values}\nThe acknowledgement does not read the EQ back",
            )
        )

    def _on_equalizer_save_clicked(self, _button):
        if self._disposed or self._busy["equalizer_save"]:
            return
        name = self._eq_name_entry.get_text().strip()
        gains = self._current_equalizer_gains()
        if not name:
            self._eq_name_entry.grab_focus()
            return
        self._eq_save_button.set_sensitive(False)

        def save():
            return save_equalizer_preset(name, gains), name, gains

        self._run_in_background("equalizer_save", save, self._show_equalizer_saved)

    def _show_equalizer_saved(self, presets, error):
        self._eq_save_button.set_sensitive(True)
        if error:
            self._eq_status.set_text(self._text("Preset konnte nicht gespeichert werden", "Could not save preset"))
            self._eq_status.set_tooltip_text(error)
            return
        presets, name, gains = presets
        self._eq_name_entry.set_text("")
        self._show_equalizer_presets(presets, None)
        if self._current_equalizer_gains() == gains:
            self._eq_loading = True
            self._eq_combo.set_active(list(presets).index(name))
            self._eq_combo.set_tooltip_text(None)
            self._eq_loading = False

    def _build_microphone_equalizer_controls(self):
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
        )
        box.set_size_request(520, -1)
        self._mic_eq_loading = False
        self._mic_eq_presets = {}
        title = Gtk.Label(
            label=self._text("Mikrofon-Equalizer", "Microphone equalizer")
        )
        title.add_css_class("title-2")
        box.append(title)
        self._mic_eq_combo = Gtk.ComboBoxText()
        self._mic_eq_combo.set_sensitive(False)
        self._mic_eq_combo.connect(
            "changed", self._on_microphone_eq_preset_changed
        )
        box.append(self._mic_eq_combo)
        self._mic_eq_scales = []
        for band in MICROPHONE_EQ_BANDS:
            row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            label = Gtk.Label(label=band)
            label.set_size_request(64, -1)
            scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, -6, 6, 0.5
            )
            scale.set_digits(1)
            scale.set_draw_value(False)
            scale.set_value(0)
            scale.set_hexpand(True)
            scale.set_sensitive(False)
            value = Gtk.Label(label="0 dB")
            value.set_size_request(48, -1)
            scale.connect(
                "value-changed",
                self._on_microphone_eq_gain_changed,
                value,
            )
            row.append(label)
            row.append(scale)
            row.append(value)
            box.append(row)
            self._mic_eq_scales.append(scale)

        actions = Gtk.Box(spacing=8)
        self._mic_eq_name_entry = Gtk.Entry()
        self._mic_eq_name_entry.set_placeholder_text(
            self._text(
                "Name für eigenes Mikrofon-Preset",
                "Name for custom microphone preset",
            )
        )
        self._mic_eq_name_entry.set_hexpand(True)
        self._mic_eq_save_button = Gtk.Button(
            label=self._text("Speichern", "Save")
        )
        self._mic_eq_save_button.set_sensitive(False)
        self._mic_eq_save_button.connect(
            "clicked", self._on_microphone_eq_save_clicked
        )
        actions.append(self._mic_eq_name_entry)
        actions.append(self._mic_eq_save_button)
        box.append(actions)
        self._mic_eq_status = Gtk.Label(
            label=self._text(
                "Aktueller Mikrofon-EQ unbekannt",
                "Current microphone EQ unknown",
            )
        )
        self._mic_eq_status.add_css_class("dim-label")
        box.append(self._mic_eq_status)
        note = Gtk.Label(
            label=self._text(
                "Unabhängig vom Wiedergabe-EQ · −6 bis +6 dB",
                "Independent of playback EQ · −6 to +6 dB",
            )
        )
        note.add_css_class("dim-label")
        box.append(note)
        return box

    def _current_microphone_eq_gains(self) -> list[float]:
        return [round(scale.get_value() * 2) / 2 for scale in self._mic_eq_scales]

    def _on_microphone_eq_gain_changed(self, scale, value_label):
        gain = round(scale.get_value() * 2) / 2
        value_label.set_text(f"{gain:+.1f} dB")
        if self._mic_eq_loading:
            return
        self._mark_equalizer_custom(True)
        self._apply_microphone_equalizer()

    def _on_microphone_eq_preset_changed(self, combo):
        if self._mic_eq_loading:
            return
        if not 0 <= combo.get_active() < len(self._mic_eq_presets):
            return
        name = combo.get_active_text()
        if name not in self._mic_eq_presets:
            return
        combo.set_tooltip_text(None)
        self._mic_eq_loading = True
        for scale, gain in zip(
            self._mic_eq_scales, self._mic_eq_presets[name]
        ):
            scale.set_value(gain)
        self._mic_eq_loading = False
        self._apply_microphone_equalizer()

    def _refresh_microphone_equalizer_presets(self):
        self._run_in_background(
            "microphone_equalizer",
            read_microphone_equalizer_presets,
            self._show_microphone_equalizer_presets,
        )

    def _show_microphone_equalizer_presets(self, presets, error):
        if error:
            self._mic_eq_preset_error = error
            self._mic_eq_status.set_text(
                self._text(
                    "Mikrofon-EQ-Presets nicht verfügbar",
                    "Microphone EQ presets unavailable",
                )
            )
            self._mic_eq_status.set_tooltip_text(error)
            self._mic_eq_save_button.set_sensitive(False)
            return
        self._mic_eq_preset_error = None
        old_count = len(self._mic_eq_presets)
        old_index = self._mic_eq_combo.get_active()
        selected = self._mic_eq_combo.get_active_text()
        self._mic_eq_presets = presets
        self._mic_eq_loading = True
        self._mic_eq_combo.remove_all()
        for name in presets:
            self._mic_eq_combo.append_text(name)
        self._append_equalizer_placeholders(self._mic_eq_combo)
        if 0 <= old_index < old_count and selected in presets:
            self._mic_eq_combo.set_active(list(presets).index(selected))
        elif old_index == old_count:
            self._mic_eq_combo.set_active(len(presets))
        self._mic_eq_loading = False
        self._select_initial_equalizer_preset(True)
        self._mic_eq_combo.set_sensitive(self._mic_eq_read_ready)
        for scale in self._mic_eq_scales:
            scale.set_sensitive(self._mic_eq_read_ready)
        self._mic_eq_save_button.set_sensitive(self._mic_eq_read_ready)

    def _append_equalizer_placeholders(self, combo):
        combo.append_text(self._text("Eigene Kurve", "Custom curve"))

    def _set_equalizer_selection(self, microphone, index, placeholder=None, tooltip=None):
        combo = self._mic_eq_combo if microphone else self._eq_combo
        presets = self._mic_eq_presets if microphone else self._eq_presets
        if microphone:
            self._mic_eq_loading = True
        else:
            self._eq_loading = True
        if placeholder is not None:
            combo.remove(len(presets))
            combo.append_text(placeholder)
        combo.set_active(index)
        combo.set_tooltip_text(tooltip)
        if microphone:
            self._mic_eq_loading = False
        else:
            self._eq_loading = False

    def _select_initial_equalizer_preset(self, microphone):
        presets = self._mic_eq_presets if microphone else self._eq_presets
        ready = self._mic_eq_read_ready if microphone else self._eq_read_ready
        initialized = (
            self._mic_eq_selection_initialized if microphone
            else self._eq_selection_initialized
        )
        if not presets or not ready or initialized:
            return
        error = self._mic_eq_read_error if microphone else self._eq_read_error
        gains = (
            self._current_microphone_eq_gains() if microphone
            else self._current_equalizer_gains()
        )
        matches = [name for name, curve in presets.items() if curve == gains] if not error else []
        if error:
            index = len(presets)
            placeholder = self._text("Nicht ausgelesen", "Not read")
            tooltip = None
        elif len(matches) == 1:
            index = list(presets).index(matches[0])
            placeholder = None
            tooltip = self._text(
                "Die Kurve passt zum Preset; der aktive Presetname wird nicht ausgelesen",
                "The curve matches this preset; the active preset name is not read back",
            )
        elif matches:
            index = len(presets)
            placeholder = self._text("Mehrere passende Presets", "Multiple matching presets")
            tooltip = ", ".join(matches)
        else:
            index = len(presets)
            placeholder = self._text("Eigene Kurve", "Custom curve")
            tooltip = None
        self._set_equalizer_selection(microphone, index, placeholder, tooltip)
        if microphone:
            self._mic_eq_selection_initialized = True
        else:
            self._eq_selection_initialized = True

    def _mark_equalizer_custom(self, microphone):
        presets = self._mic_eq_presets if microphone else self._eq_presets
        if presets:
            self._set_equalizer_selection(
                microphone, len(presets), self._text("Eigene Kurve", "Custom curve")
            )

    def _apply_microphone_equalizer(self):
        gains = self._current_microphone_eq_gains()
        name = self._mic_eq_combo.get_active_text()
        factory_preset = (
            name
            if name in FACTORY_MICROPHONE_EQ_PRESETS
            and gains == self._mic_eq_presets.get(name)
            else None
        )
        self._queue_auto_apply(
            "microphone_equalizer",
            lambda: (
                apply_microphone_equalizer(gains, factory_preset),
                gains,
            )[1],
            self._show_microphone_equalizer_applied,
            self._mic_eq_status,
        )

    def _show_microphone_equalizer_applied(self, gains, error):
        if error:
            self._mic_eq_status.set_text(
                self._text("Mikrofon-EQ-Fehler", "Microphone EQ error")
            )
            self._mic_eq_status.set_tooltip_text(error)
            return
        self._mic_eq_status.set_text(
            self._text(
                "Mikrofon-EQ-Profil angenommen",
                "Microphone EQ profile accepted",
            )
        )
        values = ", ".join(
            f"{band}: {gain:+.1f} dB"
            for band, gain in zip(MICROPHONE_EQ_BANDS, gains)
        )
        self._mic_eq_status.set_tooltip_text(
            self._text(
                f"Gesendet: {values}\nDie Bestätigung liest den Mikrofon-EQ nicht erneut aus",
                f"Sent: {values}\nThe acknowledgement does not read the microphone EQ back",
            )
        )

    def _on_microphone_eq_save_clicked(self, _button):
        if self._disposed or self._busy["microphone_equalizer_save"]:
            return
        name = self._mic_eq_name_entry.get_text().strip()
        gains = self._current_microphone_eq_gains()
        if not name:
            self._mic_eq_name_entry.grab_focus()
            return
        self._mic_eq_save_button.set_sensitive(False)

        def save():
            return save_microphone_equalizer_preset(name, gains), name, gains

        self._run_in_background(
            "microphone_equalizer_save",
            save,
            self._show_microphone_equalizer_saved,
        )

    def _show_microphone_equalizer_saved(self, result, error):
        self._mic_eq_save_button.set_sensitive(True)
        if error:
            self._mic_eq_status.set_text(
                self._text(
                    "Mikrofon-Preset konnte nicht gespeichert werden",
                    "Could not save microphone preset",
                )
            )
            self._mic_eq_status.set_tooltip_text(error)
            return
        presets, name, gains = result
        self._mic_eq_name_entry.set_text("")
        self._show_microphone_equalizer_presets(presets, None)
        if self._current_microphone_eq_gains() == gains:
            self._mic_eq_loading = True
            self._mic_eq_combo.set_active(list(presets).index(name))
            self._mic_eq_combo.set_tooltip_text(None)
            self._mic_eq_loading = False

    def _on_sidetone_changed(self, scale):
        level = round(scale.get_value())
        percent = round(level * 100 / 6)
        self._sidetone_label.set_text(f"Sidetone: {percent}%")
        if self._loading_status:
            return
        self._queue_auto_apply(
            "sidetone",
            lambda: (set_sidetone(level), level)[1],
            self._show_sidetone_result,
            self._sidetone_status,
        )

    def _show_sidetone_result(self, level, error):
        if error:
            self._sidetone_status.set_text(self._text("Sidetone-Fehler", "Sidetone error"))
            self._sidetone_status.set_tooltip_text(error)
        else:
            percent = round(level * 100 / 6)
            self._sidetone_status.set_text(
                self._text(f"Zuletzt gesetzt: {percent}%", f"Last set: {percent}%")
            )
            self._sidetone_status.set_tooltip_text(
                self._text("Die Bestätigung liest den Pegel nicht erneut aus", "The acknowledgement does not read the level back")
            )

    def _queue_auto_apply(self, key, function, callback, status_label):
        if self._disposed:
            return
        self._auto_pending[key] = (function, callback)
        status_label.set_text(self._text("Wird angewendet …", "Applying …"))
        status_label.set_tooltip_text(None)
        if key in self._auto_timers:
            GLib.source_remove(self._auto_timers[key])
        self._auto_timers[key] = GLib.timeout_add(
            AUTO_APPLY_DELAY_MS, self._start_auto_apply, key
        )

    def _start_auto_apply(self, key):
        self._auto_timers.pop(key, None)
        if self._disposed or self._busy[key] or key not in self._auto_pending:
            return GLib.SOURCE_REMOVE
        function, callback = self._auto_pending.pop(key)

        def finish(result, error):
            if error or key not in self._auto_pending:
                callback(result, error)

        self._run_in_background(key, function, finish)
        return GLib.SOURCE_REMOVE

    def _run_in_background(self, key, function, callback):
        if self._disposed or self._busy[key]:
            return
        self._busy[key] = True

        def worker():
            try:
                if key in HID_WORK_KEYS:
                    with self._hid_lock:
                        result = function()
                else:
                    result = function()
                error = None
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
                json.JSONDecodeError,
            ) as exception:
                result = None
                error = str(exception)

            def finish():
                self._busy[key] = False
                if not self._disposed:
                    callback(result, error)
                    if key in self._auto_pending and key not in self._auto_timers:
                        self._start_auto_apply(key)
                    if self._closing:
                        if error and key in AUTO_APPLY_KEYS | SAVE_KEYS:
                            self._closing = False
                            self.set_sensitive(True)
                        else:
                            self._finish_close_if_ready()
                return GLib.SOURCE_REMOVE

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_close_request(self, _window):
        if self._allow_close:
            return False
        if not self._auto_pending and not any(
            self._busy[key] for key in AUTO_APPLY_KEYS | SAVE_KEYS
        ):
            return False
        self._closing = True
        self.set_sensitive(False)
        for key, timer in list(self._auto_timers.items()):
            GLib.source_remove(timer)
            self._auto_timers.pop(key)
            self._start_auto_apply(key)
        self._finish_close_if_ready()
        return True

    def _finish_close_if_ready(self):
        if self._closing and not self._auto_pending and not any(
            self._busy[key] for key in AUTO_APPLY_KEYS | SAVE_KEYS
        ):
            self._allow_close = True
            self.close()

    def _refresh_device_settings(self):
        for setting in READ_SETTINGS:
            self._run_in_background(
                f"read-{setting}",
                lambda setting=setting: read_device_setting(setting),
                lambda value, error, setting=setting: self._show_device_setting(
                    setting, value, error
                ),
            )

    def _show_device_setting(self, setting, value, error):
        if setting == "noise-gate":
            self._noise_gate_read_ready = True
            self._noise_gate_initial_id = value
            self._noise_gate_read_error = error
            self._finish_initial_noise_gate()
            return
        controls = {
            "sidetone": (self._sidetone_scale, self._sidetone_status),
            "brightness": (self._brightness_scale, self._brightness_status),
            "sleep": (self._sleep_combo, self._sleep_status),
            "sound": (self._sound_combo, self._sound_status),
        }
        if setting in controls:
            widget, status = controls[setting]
            if error:
                status.set_text(self._text("Auslesen fehlgeschlagen", "Read failed"))
                status.set_tooltip_text(error)
            else:
                self._loading_status = True
                if setting in ("sidetone", "brightness"):
                    widget.set_value(value)
                elif setting == "sleep":
                    label = next(label for label, item in SLEEP_TIMEOUTS.items() if item == ("off" if value == 0 else str(value)))
                    widget.set_active(list(SLEEP_TIMEOUTS).index(label))
                else:
                    mode = {0: "off", 1: "all", 2: "minimal"}[value]
                    label = next(label for label, item in SOUND_MODES.items() if item == mode)
                    widget.set_active(list(SOUND_MODES).index(label))
                self._loading_status = False
                status.set_text(self._text("Vom Headset ausgelesen", "Read from headset"))
                status.set_tooltip_text(None)
            widget.set_sensitive(True)
            return

        microphone = setting == "microphone-eq"
        scales = self._mic_eq_scales if microphone else self._eq_scales
        combo = self._mic_eq_combo if microphone else self._eq_combo
        save_button = self._mic_eq_save_button if microphone else self._eq_save_button
        status = self._mic_eq_status if microphone else self._eq_status
        presets = self._mic_eq_presets if microphone else self._eq_presets
        preset_error = self._mic_eq_preset_error if microphone else self._eq_preset_error
        if microphone:
            self._mic_eq_read_ready = True
            self._mic_eq_read_error = error
            self._mic_eq_loading = True
        else:
            self._eq_read_ready = True
            self._eq_read_error = error
            self._eq_loading = True
        if not error:
            for scale, gain in zip(scales, value):
                scale.set_value(gain)
        if microphone:
            self._mic_eq_loading = False
        else:
            self._eq_loading = False
        self._select_initial_equalizer_preset(microphone)
        if not preset_error:
            if error:
                status.set_text(self._text("EQ-Auslesen fehlgeschlagen", "EQ read failed"))
                status.set_tooltip_text(error)
            else:
                status.set_text(self._text("EQ-Kurve ausgelesen", "EQ curve read"))
                status.set_tooltip_text(None)
        enabled = bool(presets) and not preset_error
        combo.set_sensitive(enabled)
        save_button.set_sensitive(enabled)
        for scale in scales:
            scale.set_sensitive(enabled)

    def _finish_initial_noise_gate(self):
        if not self._noise_gate_read_ready or not self._noise_gate_list_ready:
            return
        if self._noise_gate_read_error:
            self._noise_gate_status.set_text(self._text("Auslesen fehlgeschlagen", "Read failed"))
            self._noise_gate_status.set_tooltip_text(self._noise_gate_read_error)
        else:
            state = next(
                name for name, state_id in MICROPHONE_NOISE_GATE_IDS.items()
                if state_id == self._noise_gate_initial_id
            )
            self._loading_status = True
            self._noise_gate_combo.set_active(list(MICROPHONE_NOISE_GATE_IDS).index(state))
            self._loading_status = False
            self._noise_gate_status.set_text(self._text("Vom Headset ausgelesen", "Read from headset"))
            self._noise_gate_status.set_tooltip_text(None)
        self._noise_gate_combo.set_sensitive(True)

    def _refresh_battery(self):
        self._run_in_background("battery", read_battery, self._show_battery)
        return GLib.SOURCE_REMOVE

    def _refresh_battery_timer(self):
        self._refresh_battery()
        return GLib.SOURCE_CONTINUE

    def _set_battery_color(self, css_class):
        for name in BATTERY_COLOR_CLASSES:
            self._battery_icon.remove_css_class(name)
        if css_class:
            self._battery_icon.add_css_class(css_class)

    def _show_battery(self, status, error):
        if error:
            self._battery_icon.set_from_icon_name("battery-missing-symbolic")
            self._set_battery_color(None)
            self._battery_percent.set_text("A50 --%")
            self._battery_state.set_text(self._text("Akku nicht verfügbar", "Battery unavailable"))
            self._battery_state.set_tooltip_text(error)
            return
        level = status["level"]
        charging = status["charging"]
        self._battery_icon.set_from_icon_name(battery_icon(level, charging))
        self._set_battery_color(battery_color_class(level, charging))
        self._battery_percent.set_text(f"A50 {level}%")
        state = self._text("Lädt", "Charging") if charging else self._text("Lädt nicht", "Not charging")
        self._battery_state.set_text(state)
        self._battery_state.set_tooltip_text(
            self._text("Akkustand experimentell", "Battery reading is experimental")
        )

    def _refresh_microphone(self):
        self._run_in_background(
            "microphone", read_microphone_states, self._show_microphone
        )
        return GLib.SOURCE_REMOVE

    def _refresh_microphone_timer(self):
        self._refresh_microphone()
        return GLib.SOURCE_CONTINUE

    def _show_microphone(self, sources, error):
        if error:
            self._mic_state = None
            self._mic_icon.set_from_icon_name("audio-input-microphone-symbolic")
            self._mic_state_label.set_text(
                self._text("Nicht verfügbar", "Unavailable")
            )
            self._mic_button.set_sensitive(False)
            self._mic_button.set_tooltip_text(error)
            return

        self._mic_state = microphone_state(sources)
        self._mic_button.set_sensitive(True)
        if self._mic_state == "muted":
            icon = "microphone-disabled-symbolic"
            label = self._text("Stumm", "Muted")
        elif self._mic_state == "unmuted":
            icon = "microphone-sensitivity-high-symbolic"
            label = self._text("Aktiv", "On")
        else:
            icon = "audio-input-microphone-symbolic"
            label = self._text("Gemischt", "Mixed")
        self._mic_icon.set_from_icon_name(icon)
        self._mic_state_label.set_text(label)
        self._mic_button.set_tooltip_text(
            self._text(
                "Klicken, um beide A50-Mikrofone umzuschalten",
                "Click to toggle both A50 microphones",
            )
        )

    def _on_microphone_clicked(self, _button):
        if self._busy["microphone"] or self._mic_state is None:
            return
        self._mic_button.set_sensitive(False)

        def update():
            toggle_microphones()
            return read_microphone_states()

        self._run_in_background("microphone", update, self._show_microphone)

    def do_unroot(self):
        self._disposed = True
        for timer in self._auto_timers.values():
            GLib.source_remove(timer)
        self._auto_timers.clear()
        self._auto_pending.clear()
        if self._battery_timer:
            GLib.source_remove(self._battery_timer)
        if self._microphone_timer:
            GLib.source_remove(self._microphone_timer)
        if self._bluetooth_timer:
            GLib.source_remove(self._bluetooth_timer)
        super().do_unroot()


class A50ControlApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.astro_a50_linux.Control",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(BATTERY_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = A50ControlWindow(self)
        window.present()


def main():
    Adw.init()
    application = A50ControlApplication()
    return application.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
