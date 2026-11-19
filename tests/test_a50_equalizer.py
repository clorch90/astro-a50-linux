import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_equalizer.py"
spec = importlib.util.spec_from_file_location("a50_equalizer", SCRIPT)
assert spec and spec.loader
equalizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(equalizer)


class EqualizerTest(unittest.TestCase):
    def test_standard_preset_uses_neutral_factory_report(self):
        self.assertEqual(len(equalizer.FACTORY_PROFILE_TEMPLATE), 64)
        standard = equalizer.build_report(
            equalizer.PRESETS["Standard"], equalizer.FACTORY_PROFILE_TEMPLATE
        )
        self.assertEqual(
            standard,
            bytes.fromhex(
                "02 0c 38 00 0d 2d 01 03 00 00 "
                "14 16 00 78 00 32 16 00 78 00 7d 16 00 78 00 fa 16 00 78 01 "
                "f4 16 00 78 03 e8 16 00 78 09 c4 16 00 78 13 88 16 00 78 27 "
                "10 16 00 78 4e 20 16 00 78 00 00 00 00 00"
            ),
        )

    def test_build_report_matches_captured_standard_and_50hz_profiles(self):
        standard = equalizer.build_report([0] * 10)
        bass_50 = equalizer.build_report([0, 3, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(len(standard), 64)
        self.assertEqual(standard[:10], bytes.fromhex("02 0c 38 00 0d 2d 01 03 00 00"))
        differences = [
            (index, before, after)
            for index, (before, after) in enumerate(zip(standard, bass_50))
            if before != after
        ]
        self.assertEqual(differences, [(18, 0x78, 0xb4)])

    def test_build_report_encodes_confirmed_20hz_and_1khz_gains(self):
        report = equalizer.build_report([3, 0, 0, 0, 0, -3, 0, 0, 0, 0])
        self.assertEqual(report[12:14], bytes.fromhex("00 b4"))
        self.assertEqual(report[37:39], bytes.fromhex("00 3c"))

    def test_build_report_encodes_half_db_gains(self):
        report = equalizer.build_report([0.5, -0.5] + [0] * 8)
        self.assertEqual(report[12:14], bytes.fromhex("00 82"))
        self.assertEqual(report[17:19], bytes.fromhex("00 6e"))
        extremes = equalizer.build_report([-6, 6] + [0] * 8)
        self.assertEqual(extremes[12:14], bytes.fromhex("00 00"))
        self.assertEqual(extremes[17:19], bytes.fromhex("00 f0"))

    def test_rejects_wrong_gain_count_and_unverified_range(self):
        with self.assertRaises(ValueError):
            equalizer.build_report([0] * 9)
        for gains in (
            [6.5] + [0] * 9,
            [-6.5] + [0] * 9,
            [0.25] + [0] * 9,
            [True] + [0] * 9,
        ):
            with self.subTest(gains=gains), self.assertRaises(ValueError):
                equalizer.build_report(gains)

    def test_saves_and_reloads_only_custom_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                gains = [0, 3, 0, 0, 0, -0.5, 0, 0, 0, 0]
                equalizer.save_preset("My EQ", gains)
                self.assertEqual(equalizer.load_presets()["My EQ"], gains)
                content = json.loads(equalizer.config_path().read_text())
                self.assertEqual(content, {"My EQ": gains})
                equalizer.delete_preset("My EQ")
                self.assertNotIn("My EQ", equalizer.load_presets())
                self.assertIn("Standard", equalizer.load_presets())
                self.assertNotIn("Flat", equalizer.load_presets())

    def test_reserved_names_and_invalid_saved_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                with self.assertRaises(ValueError):
                    equalizer.save_preset("Standard", [0] * 10)
                equalizer.config_path().parent.mkdir(parents=True)
                equalizer.config_path().write_text(json.dumps({"Bad": [0] * 9}))
                with self.assertRaises(ValueError):
                    equalizer.load_presets()

    def test_device_failure_is_reported_by_cli(self):
        with (
            patch.object(equalizer, "set_equalizer", side_effect=OSError("device unavailable")),
            patch("sys.argv", ["a50-equalizer", "apply-values", *("0" for _ in range(10))]),
            patch("sys.stderr") as stderr,
        ):
            self.assertEqual(equalizer.main(), 1)
            self.assertIn("device unavailable", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_factory_apply_uses_captured_factory_report_template(self):
        with (
            patch.object(equalizer, "load_presets", return_value=equalizer.PRESETS),
            patch.object(equalizer, "set_equalizer") as set_equalizer,
            patch("sys.argv", ["a50-equalizer", "apply", "Standard"]),
        ):
            self.assertEqual(equalizer.main(), 0)
        set_equalizer.assert_called_once_with(
            equalizer.PRESETS["Standard"], equalizer.FACTORY_PROFILE_TEMPLATE
        )

    def test_original_preset_uses_custom_report_template(self):
        with (
            patch.object(equalizer, "load_presets", return_value=equalizer.PRESETS),
            patch.object(equalizer, "set_equalizer") as set_equalizer,
            patch("sys.argv", ["a50-equalizer", "apply", "Bass"]),
        ):
            self.assertEqual(equalizer.main(), 0)
        set_equalizer.assert_called_once_with(
            equalizer.PRESETS["Bass"], equalizer.PROFILE_TEMPLATE
        )

    def test_send_hid_report_accepts_factory_profile_response_id(self):
        response_prefix = bytes.fromhex("02 0c 04 00 14 00 01")
        response = response_prefix + bytes(57)
        with (
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}),
            patch.object(Path, "open", autospec=True),
            patch.object(equalizer.fcntl, "flock"),
            patch.object(equalizer.os, "open", return_value=42),
            patch.object(equalizer.os, "write", return_value=64) as write,
            patch.object(equalizer.os, "read", return_value=response),
            patch.object(equalizer.os, "close"),
            patch.object(equalizer.select, "select", return_value=([42], [], [])),
        ):
            equalizer.send_hid_report(
                bytes(64), response_prefix, response_status=1
            )
        write.assert_called_once_with(42, bytes(64))


if __name__ == "__main__":
    unittest.main()
