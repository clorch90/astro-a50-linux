import importlib.util
import json
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "gui" / "a50_control.py"
spec = importlib.util.spec_from_file_location("a50_control", SCRIPT)
assert spec and spec.loader
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def node(node_id, name, muted):
    return {
        "id": node_id,
        "info": {
            "props": {
                "node.name": name,
                "media.class": "Audio/Source",
            },
            "params": {"Props": [{"mute": muted}]},
        },
    }


class A50ControlTest(unittest.TestCase):
    def test_sidebar_switches_pages_without_losing_edits_or_sending_commands(self):
        if not control.Gtk.init_check():
            self.skipTest("GTK display unavailable")
        control.Adw.init()
        application = control.Adw.Application(
            application_id="io.github.astro_a50_linux.ControlTest",
            flags=control.Gio.ApplicationFlags.NON_UNIQUE,
        )
        application.register()
        with (
            patch.object(control.A50ControlWindow, "_run_in_background"),
            patch.object(control.A50ControlWindow, "_queue_auto_apply"),
            patch.object(control.subprocess, "run") as run,
        ):
            window = control.A50ControlWindow(application)
            self.addCleanup(window.destroy)
            pages = window._pages
            sidebar = window.get_content().get_content().get_first_child()
            self.assertIs(sidebar.get_stack(), pages)
            self.assertEqual(pages.get_visible_child_name(), "settings")

            settings = pages.get_child_by_name("settings")
            output = pages.get_child_by_name("output-eq")
            microphone = pages.get_child_by_name("microphone-eq")
            for page in (settings, output, microphone):
                self.assertIsInstance(page, control.Gtk.ScrolledWindow)
            self.assertTrue(window._sidetone_scale.is_ancestor(settings))
            self.assertTrue(window._brightness_scale.is_ancestor(settings))
            self.assertTrue(window._noise_gate_combo.is_ancestor(settings))
            self.assertTrue(window._eq_scales[0].is_ancestor(output))
            self.assertTrue(window._mic_eq_scales[0].is_ancestor(microphone))

            rows = sidebar.get_first_child().get_child().get_child()
            rows.select_row(rows.get_row_at_index(1))
            self.assertEqual(pages.get_visible_child_name(), "output-eq")
            window._eq_scales[0].set_value(2)
            rows.select_row(rows.get_row_at_index(2))
            self.assertEqual(pages.get_visible_child_name(), "microphone-eq")
            window._mic_eq_scales[0].set_value(-2)
            rows.select_row(rows.get_row_at_index(0))
            self.assertEqual(pages.get_visible_child_name(), "settings")
            self.assertEqual(window._eq_scales[0].get_value(), 2)
            self.assertEqual(window._mic_eq_scales[0].get_value(), -2)
            run.assert_not_called()

    def test_microphone_state_reports_muted_unmuted_and_mixed(self):
        voice, game = sorted(control.SOURCE_NAMES)
        self.assertEqual(
            control.microphone_state({voice: (1, True), game: (2, True)}),
            "muted",
        )
        self.assertEqual(
            control.microphone_state({voice: (1, False), game: (2, False)}),
            "unmuted",
        )
        self.assertEqual(
            control.microphone_state({voice: (1, True), game: (2, False)}),
            "mixed",
        )

    def test_reads_both_a50_mute_states(self):
        voice, game = sorted(control.SOURCE_NAMES)
        output = json.dumps([
            node(7, voice, True),
            node(8, game, False),
            node(9, "unrelated", False),
        ])
        with patch.object(
            control.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["pw-dump"], 0, stdout=output, stderr=""
            ),
        ):
            self.assertEqual(
                control.read_microphone_states(),
                {voice: (7, True), game: (8, False)},
            )

    def test_missing_microphone_source_is_an_error(self):
        voice = next(iter(control.SOURCE_NAMES))
        output = json.dumps([node(7, voice, True)])
        with (
            patch.object(
                control.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    ["pw-dump"], 0, stdout=output, stderr=""
                ),
            ),
            self.assertRaises(RuntimeError),
        ):
            control.read_microphone_states()

    def test_battery_color_class(self):
        self.assertEqual(control.battery_color_class(95, True), "a50-battery-charging")
        self.assertEqual(control.battery_color_class(100, True), "a50-battery-full")
        self.assertEqual(control.battery_color_class(20, False), "a50-battery-low")
        self.assertEqual(control.battery_color_class(40, False), "a50-battery-medium")
        self.assertIsNone(control.battery_color_class(99, False))

    def test_sidetone_command_failure_is_reported(self):
        result = subprocess.CompletedProcess(["a50-sidetone", "2"], 1, stdout="", stderr="Device unavailable")
        with (
            patch.object(control.subprocess, "run", return_value=result) as run,
            self.assertRaisesRegex(RuntimeError, "Device unavailable"),
        ):
            control.set_sidetone(2)
        self.assertEqual(run.call_args.args[0], [str(control.SIDETONE_COMMAND), "2"])

    def test_reads_and_validates_equalizer_presets(self):
        presets = {
            "Standard": [0] * 10,
            "Bass": [3, 3, 2, 1, 0, 0, 0, 0, 0, 0],
        }
        result = subprocess.CompletedProcess(
            ["a50-equalizer", "list"], 0, stdout=json.dumps(presets), stderr=""
        )
        with patch.object(control.subprocess, "run", return_value=result) as run:
            self.assertEqual(control.read_equalizer_presets(), presets)
        self.assertEqual(run.call_args.args[0], [str(control.EQUALIZER_COMMAND), "list"])

        invalid = subprocess.CompletedProcess(
            ["a50-equalizer", "list"],
            0,
            stdout=json.dumps({"Broken": [0.25] + [0] * 9}),
            stderr="",
        )
        with (
            patch.object(control.subprocess, "run", return_value=invalid),
            self.assertRaisesRegex(ValueError, "Invalid EQ preset data"),
        ):
            control.read_equalizer_presets()

    def test_apply_factory_equalizer_uses_named_preset(self):
        gains = [0] * 10
        result = subprocess.CompletedProcess(
            ["a50-equalizer", "apply", "Standard"], 0, stdout="", stderr=""
        )
        with patch.object(
            control.subprocess, "run", return_value=result
        ) as run:
            control.apply_equalizer(gains, "Standard")
        self.assertEqual(
            run.call_args.args[0],
            [str(control.EQUALIZER_COMMAND), "apply", "Standard"],
        )

    def test_reads_and_validates_separate_microphone_eq_presets(self):
        presets = {
            "Standard": [0] * 10,
            "Warm": [0, 1, 1, 0.5, 0, 0, -0.5, -1, -1, -1],
        }
        result = subprocess.CompletedProcess(
            ["a50-microphone-equalizer", "list"],
            0,
            stdout=json.dumps(presets),
            stderr="",
        )
        with patch.object(control.subprocess, "run", return_value=result) as run:
            self.assertEqual(
                control.read_microphone_equalizer_presets(), presets
            )
        self.assertEqual(
            run.call_args.args[0],
            [str(control.MICROPHONE_EQ_COMMAND), "list"],
        )

        invalid = subprocess.CompletedProcess(
            ["a50-microphone-equalizer", "list"],
            0,
            stdout=json.dumps({"Broken": [0.25] + [0] * 9}),
            stderr="",
        )
        with (
            patch.object(control.subprocess, "run", return_value=invalid),
            self.assertRaisesRegex(ValueError, "Invalid microphone EQ preset data"),
        ):
            control.read_microphone_equalizer_presets()

    def test_applying_microphone_eq_uses_its_own_command(self):
        gains = [0.5] + [0] * 9
        result = subprocess.CompletedProcess(
            ["a50-microphone-equalizer", "apply", "Standard"],
            0,
            stdout="",
            stderr="",
        )
        with patch.object(
            control.subprocess, "run", return_value=result
        ) as run:
            control.apply_microphone_equalizer(gains, "Standard")
        self.assertEqual(
            run.call_args.args[0],
            [str(control.MICROPHONE_EQ_COMMAND), "apply", "Standard"],
        )

    def test_reads_captured_noise_gate_state_names_and_ids(self):
        states = {"Aus": 0, "Nacht": 2, "Zu Hause": 1, "Turnier": 4}
        result = subprocess.CompletedProcess(
            ["a50-microphone-noise-gate", "list"],
            0,
            stdout=json.dumps(states, ensure_ascii=False),
            stderr="",
        )
        with patch.object(control.subprocess, "run", return_value=result) as run:
            self.assertEqual(
                control.read_microphone_noise_gate_states(),
                ("Aus", "Nacht", "Zu Hause", "Turnier"),
            )
        self.assertEqual(
            run.call_args.args[0],
            [str(control.MICROPHONE_NOISE_GATE_COMMAND), "list"],
        )

        invalid = subprocess.CompletedProcess(
            ["a50-microphone-noise-gate", "list"],
            0,
            stdout=json.dumps({"Aus": 0}),
            stderr="",
        )
        with (
            patch.object(control.subprocess, "run", return_value=invalid),
            self.assertRaisesRegex(ValueError, "Invalid microphone noise-gate states"),
        ):
            control.read_microphone_noise_gate_states()

    def test_setting_noise_gate_uses_its_own_command(self):
        result = subprocess.CompletedProcess(
            ["a50-microphone-noise-gate", "set", "Nacht"],
            0,
            stdout="",
            stderr="",
        )
        with patch.object(control.subprocess, "run", return_value=result) as run:
            control.set_microphone_noise_gate("Nacht")
        self.assertEqual(
            run.call_args.args[0],
            [str(control.MICROPHONE_NOISE_GATE_COMMAND), "set", "Nacht"],
        )

    def test_base_station_controls_use_separate_command(self):
        success = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(control.subprocess, "run", return_value=success) as run:
            control.set_base_station_brightness(50)
            control.set_sleep_timeout("30 Minuten")
            control.set_headset_sound_mode("Minimal")
        self.assertEqual(
            run.call_args_list[0].args[0],
            [str(control.BASE_STATION_COMMAND), "brightness", "50"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [str(control.BASE_STATION_COMMAND), "sleep", "30"],
        )
        self.assertEqual(
            run.call_args_list[2].args[0],
            [str(control.BASE_STATION_COMMAND), "sound", "minimal"],
        )

    def test_bluetooth_status_reads_connection_and_device_name(self):
        status = {"connected": True, "device_name": "Test phone"}
        result = subprocess.CompletedProcess(
            ["a50-base-station", "bluetooth"],
            0,
            stdout=json.dumps(status),
            stderr="",
        )
        with patch.object(control.subprocess, "run", return_value=result) as run:
            self.assertEqual(control.read_bluetooth_status(), status)
        self.assertEqual(
            run.call_args.args[0],
            [str(control.BASE_STATION_COMMAND), "bluetooth"],
        )

    def test_bluetooth_status_rejects_invalid_device_data(self):
        result = subprocess.CompletedProcess(
            ["a50-base-station", "bluetooth"],
            0,
            stdout=json.dumps({"connected": False, "device_name": "stale"}),
            stderr="",
        )
        with (
            patch.object(control.subprocess, "run", return_value=result),
            self.assertRaisesRegex(ValueError, "Invalid A50 Bluetooth status"),
        ):
            control.read_bluetooth_status()

    def test_device_read_reports_command_errors(self):
        result = subprocess.CompletedProcess(
            ["a50-device-status", "brightness"], 1,
            stdout="", stderr="Device unavailable",
        )
        with (
            patch.object(control.subprocess, "run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "Device unavailable"),
        ):
            control.read_device_setting("brightness")

    def test_apply_equalizer_reports_failures(self):
        gains = [0, 3, 0, 0, 0, 0, 0, 0, 0, 0]
        result = subprocess.CompletedProcess(
            ["a50-equalizer"], 1, stdout="", stderr="Device unavailable"
        )
        with (
            patch.object(control.subprocess, "run", return_value=result) as run,
            self.assertRaisesRegex(RuntimeError, "Device unavailable"),
        ):
            control.apply_equalizer(gains)
        self.assertEqual(
            run.call_args.args[0],
            [str(control.EQUALIZER_COMMAND), "apply-values", *map(str, gains)],
        )

    def test_mute_and_battery_icons(self):
        self.assertEqual(control.battery_icon(95, True), "battery-level-90-charging-symbolic")
        self.assertEqual(control.battery_icon(100, True), "battery-level-100-charged-symbolic")
        self.assertEqual(control.battery_icon(29, False), "battery-level-20-symbolic")

    def test_toggle_mutes_both_when_unmuted_or_mixed(self):
        voice, game = sorted(control.SOURCE_NAMES)
        self.assertTrue(control.toggled_mute_state({voice: (1, False), game: (2, False)}))
        self.assertTrue(control.toggled_mute_state({voice: (1, False), game: (2, True)}))
        self.assertFalse(control.toggled_mute_state({voice: (1, True), game: (2, True)}))

    def test_toggle_mutes_both_inputs_and_plays_feedback(self):
        voice, game = sorted(control.SOURCE_NAMES)
        sources = {voice: (7, False), game: (8, True)}
        with (
            patch.object(control, "read_microphone_states", return_value=sources),
            patch.object(control.subprocess, "run") as run,
        ):
            self.assertTrue(control.toggle_microphones())
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["wpctl", "set-mute", "7", "1"],
                ["wpctl", "set-mute", "8", "1"],
                ["paplay", "--volume=65536", str(control.SOUND_DIR / "mute.wav")],
            ],
        )


class A50AutoApplyTest(unittest.TestCase):
    def setUp(self):
        if not control.Gtk.init_check():
            self.skipTest("GTK display unavailable")
        control.Adw.init()
        self.application = control.Adw.Application(
            application_id=f"io.github.astro_a50_linux.AutoApplyTest.{self._testMethodName}",
            flags=control.Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.application.register()
        with patch.object(control.A50ControlWindow, "_run_in_background"):
            self.window = control.A50ControlWindow(self.application)
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        for timer in self.window._auto_timers.values():
            control.GLib.source_remove(timer)
        self.window._auto_timers.clear()
        self.window.destroy()

    def wait_for(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        context = control.GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if condition():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for GUI operation")

    def load_options(self):
        self.window._show_equalizer_presets(
            {"Standard": [0] * 10, "Bass": [1] * 10}, None
        )
        self.window._show_microphone_equalizer_presets(
            {"Standard": [0] * 10, "Warm": [2] * 10}, None
        )
        self.window._show_microphone_noise_gate_states(
            control.MICROPHONE_NOISE_GATE_STATES, None
        )

    def test_initial_readbacks_update_controls_without_applying(self):
        window = self.window
        self.load_options()
        window._show_device_setting("sidetone", 3, None)
        window._show_device_setting("brightness", 50, None)
        window._show_device_setting("sleep", 30, None)
        window._show_device_setting("sound", 2, None)
        window._show_device_setting("noise-gate", 0, None)
        window._show_device_setting("output-eq", [1.0] * 10, None)
        window._show_device_setting("microphone-eq", [-1.5] * 10, None)
        self.assertEqual(window._sidetone_scale.get_value(), 3)
        self.assertEqual(window._sidetone_label.get_text(), "Sidetone: 50%")
        self.assertEqual(window._brightness_scale.get_value(), 50)
        self.assertEqual(window._sleep_combo.get_active_text(), "30 Minuten")
        self.assertEqual(window._sound_combo.get_active_text(), "Minimal")
        self.assertEqual(window._noise_gate_combo.get_active_text(), "Aus")
        self.assertEqual(window._current_equalizer_gains(), [1.0] * 10)
        self.assertEqual(window._current_microphone_eq_gains(), [-1.5] * 10)
        self.assertEqual(window._eq_combo.get_active_text(), "Bass")
        self.assertEqual(window._mic_eq_combo.get_active_text(), window._text("Eigene Kurve", "Custom curve"))
        self.assertIsNotNone(window._eq_combo.get_tooltip_text())
        self.assertTrue(window._eq_scales[0].get_sensitive())
        self.assertTrue(window._mic_eq_scales[0].get_sensitive())
        self.assertFalse(window._auto_pending)
        self.assertFalse(window._auto_timers)

    def test_sidetone_readback_displays_all_seven_percentages_without_applying(self):
        window = self.window
        for level, percent in enumerate((0, 17, 33, 50, 67, 83, 100)):
            with self.subTest(level=level):
                window._show_device_setting("sidetone", level, None)
                self.assertEqual(window._sidetone_scale.get_value(), level)
                self.assertEqual(window._sidetone_label.get_text(), f"Sidetone: {percent}%")
        self.assertFalse(window._auto_pending)
        self.assertFalse(window._auto_timers)

    def test_eq_readback_waits_for_presets_and_errors_leave_controls_usable(self):
        window = self.window
        window._show_device_setting("output-eq", [2] * 10, None)
        self.assertFalse(window._eq_scales[0].get_sensitive())
        window._show_equalizer_presets({"Standard": [0] * 10}, None)
        self.assertTrue(window._eq_scales[0].get_sensitive())
        self.assertEqual(window._current_equalizer_gains(), [2] * 10)
        self.assertEqual(window._eq_combo.get_active_text(), window._text("Eigene Kurve", "Custom curve"))
        window._show_microphone_equalizer_presets({"Standard": [0] * 10}, None)
        window._show_device_setting("microphone-eq", None, "Device unavailable")
        self.assertTrue(window._mic_eq_scales[0].get_sensitive())
        self.assertEqual(window._mic_eq_status.get_tooltip_text(), "Device unavailable")
        window._show_device_setting("brightness", None, "Device unavailable")
        self.assertTrue(window._brightness_scale.get_sensitive())
        self.assertEqual(window._brightness_status.get_tooltip_text(), "Device unavailable")
        self.assertFalse(window._auto_pending)

    def test_equalizer_matches_after_either_startup_order_and_distinguishes_duplicates(self):
        window = self.window
        window._show_device_setting("output-eq", [0] * 10, None)
        window._show_equalizer_presets({"Standard": [0] * 10, "Other": [1] * 10}, None)
        self.assertEqual(window._eq_combo.get_active_text(), "Standard")
        window._show_microphone_equalizer_presets(
            {"Standard": [0] * 10, "Custom": [0] * 10}, None
        )
        window._show_device_setting("microphone-eq", [0] * 10, None)
        self.assertEqual(
            window._mic_eq_combo.get_active_text(),
            window._text("Mehrere passende Presets", "Multiple matching presets"),
        )
        self.assertEqual(window._mic_eq_combo.get_tooltip_text(), "Standard, Custom")
        self.assertFalse(window._auto_pending)

    def test_manual_eq_edit_changes_selection_to_custom_and_still_applies(self):
        window = self.window
        window._show_equalizer_presets({"Standard": [0] * 10}, None)
        window._show_device_setting("output-eq", [0] * 10, None)
        self.assertEqual(window._eq_combo.get_active_text(), "Standard")
        with patch.object(control, "apply_equalizer") as output:
            window._eq_scales[0].set_value(1)
            self.assertEqual(window._eq_combo.get_active_text(), window._text("Eigene Kurve", "Custom curve"))
            self.wait_for(lambda: not window._auto_pending and not window._busy["equalizer"])
            output.assert_called_once_with([1.0] + [0.0] * 9, None)

    def test_noise_gate_readback_waits_for_options_without_applying(self):
        window = self.window
        window._show_device_setting("noise-gate", 2, None)
        self.assertFalse(window._noise_gate_combo.get_sensitive())
        window._show_microphone_noise_gate_states(control.MICROPHONE_NOISE_GATE_STATES, None)
        self.assertTrue(window._noise_gate_combo.get_sensitive())
        self.assertEqual(window._noise_gate_combo.get_active_text(), "Nacht")
        self.assertFalse(window._auto_pending)

    def test_initial_loading_does_not_apply_and_all_controls_apply_changes(self):
        window = self.window
        with (
            patch.object(control, "set_sidetone") as sidetone,
            patch.object(control, "set_base_station_brightness") as brightness,
            patch.object(control, "set_sleep_timeout") as sleep,
            patch.object(control, "set_headset_sound_mode") as sound,
            patch.object(control, "set_microphone_noise_gate") as gate,
            patch.object(control, "apply_equalizer") as output,
            patch.object(control, "apply_microphone_equalizer") as microphone,
        ):
            self.load_options()
            self.assertFalse(window._auto_pending)
            self.assertEqual(window._eq_combo.get_active(), -1)
            self.assertEqual(window._mic_eq_combo.get_active(), -1)
            self.assertEqual(window._noise_gate_combo.get_active(), -1)
            window._sidetone_scale.set_value(1)
            window._sidetone_scale.set_value(3)
            window._brightness_scale.set_value(60)
            window._brightness_scale.set_value(50)
            window._sleep_combo.set_active(2)
            window._sound_combo.set_active(1)
            window._noise_gate_combo.set_active(1)
            window._eq_combo.set_active(1)
            window._mic_eq_combo.set_active(1)
            self.wait_for(lambda: not window._auto_pending and not any(
                window._busy[key] for key in control.AUTO_APPLY_KEYS
            ))
            sidetone.assert_called_once_with(3)
            brightness.assert_called_once_with(50)
            sleep.assert_called_once_with("30 Minuten")
            sound.assert_called_once_with("Minimal")
            gate.assert_called_once_with("Nacht")
            output.assert_called_once_with([1.0] * 10, None)
            microphone.assert_called_once_with([2.0] * 10, None)

    def test_latest_value_is_sent_after_inflight_command(self):
        window = self.window
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def send(level):
            if level == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError("Test command timed out")

        with patch.object(control, "set_sidetone", side_effect=send) as sidetone:
            window._sidetone_scale.set_value(1)
            self.wait_for(started.is_set)
            window._sidetone_scale.set_value(2)
            window._sidetone_scale.set_value(4)
            self.wait_for(lambda: "sidetone" not in window._auto_timers)
            release.set()
            self.wait_for(lambda: sidetone.call_count == 2 and not window._busy["sidetone"])
            self.assertEqual([call.args for call in sidetone.call_args_list], [(1,), (4,)])
            self.assertEqual(window._sidetone_label.get_text(), "Sidetone: 67%")
            self.assertIn("67%", window._sidetone_status.get_text())

    def test_device_operations_are_serialized_and_errors_are_visible(self):
        window = self.window
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def fail_sidetone(_level):
            started.set()
            if not release.wait(3):
                raise RuntimeError("Test command timed out")
            raise RuntimeError("Device unavailable")

        with (
            patch.object(control, "set_sidetone", side_effect=fail_sidetone),
            patch.object(control, "set_base_station_brightness") as brightness,
        ):
            window._sidetone_scale.set_value(1)
            self.wait_for(started.is_set)
            window._brightness_scale.set_value(50)
            self.wait_for(lambda: window._busy["brightness"])
            brightness.assert_not_called()
            release.set()
            self.wait_for(lambda: not window._busy["sidetone"] and not window._busy["brightness"])
            brightness.assert_called_once_with(50)
            self.assertEqual(window._sidetone_status.get_tooltip_text(), "Device unavailable")

    def test_closing_flushes_pending_change_and_waits_for_completion(self):
        window = self.window
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def send(_level):
            started.set()
            if not release.wait(3):
                raise RuntimeError("Test command timed out")

        with patch.object(control, "set_sidetone", side_effect=send) as sidetone:
            window._sidetone_scale.set_value(2)
            self.assertTrue(window._on_close_request(window))
            self.wait_for(started.is_set)
            self.assertTrue(window._closing)
            self.assertFalse(window._allow_close)
            release.set()
            self.wait_for(lambda: window._allow_close)
            sidetone.assert_called_once_with(2)

    def test_close_failure_keeps_window_open_and_shows_error(self):
        window = self.window
        with patch.object(control, "set_sidetone", side_effect=RuntimeError("Device unavailable")):
            window._sidetone_scale.set_value(2)
            self.assertTrue(window._on_close_request(window))
            self.wait_for(lambda: not window._closing)
            self.assertFalse(window._allow_close)
            self.assertTrue(window.get_sensitive())
            self.assertEqual(window._sidetone_status.get_tooltip_text(), "Device unavailable")

    def test_neutral_presets_can_be_selected_and_microphone_bands_auto_apply(self):
        window = self.window
        self.load_options()
        with (
            patch.object(control, "apply_equalizer") as output,
            patch.object(control, "apply_microphone_equalizer") as microphone,
        ):
            window._eq_combo.set_active(0)
            window._mic_eq_combo.set_active(0)
            self.wait_for(lambda: not window._auto_pending and not any(
                window._busy[key] for key in ("equalizer", "microphone_equalizer")
            ))
            output.assert_called_once_with([0.0] * 10, "Standard")
            microphone.assert_called_once_with([0.0] * 10, "Standard")
            window._mic_eq_scales[0].set_value(-1.5)
            self.wait_for(lambda: not window._auto_pending and not window._busy["microphone_equalizer"])
            self.assertEqual(microphone.call_args.args, ([-1.5] + [0.0] * 9, None))

    def test_saved_presets_do_not_send_or_replace_newer_edits(self):
        window = self.window
        self.load_options()
        with patch.object(control, "apply_equalizer") as output:
            window._eq_scales[0].set_value(3)
            window._show_equalizer_saved(
                ({"Standard": [0] * 10, "Custom": [1] * 10}, "Custom", [1] * 10),
                None,
            )
            self.assertEqual(window._eq_scales[0].get_value(), 3)
            self.wait_for(lambda: not window._auto_pending and not window._busy["equalizer"])
            output.assert_called_once_with([3.0] + [0.0] * 9, None)


if __name__ == "__main__":
    unittest.main()
