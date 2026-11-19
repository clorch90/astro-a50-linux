import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "a50_microphone_equalizer.py"
)
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("a50_microphone_equalizer", SCRIPT)
assert spec and spec.loader
microphone_eq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(microphone_eq)


class MicrophoneEqualizerTest(unittest.TestCase):
    def test_custom_report_matches_captured_flat_mic_eq_template(self):
        report = microphone_eq.build_report([0] * 10)
        self.assertEqual(len(report), 64)
        self.assertEqual(
            report,
            bytes.fromhex(
                "02 0c 38 00 0d 2d 00 03 00 00 "
                "50 00 00 78 00 96 00 00 78 00 fa 00 00 78 01 90 00 00 78 03 "
                "20 00 00 78 05 dc 00 00 78 09 c4 00 00 78 13 88 00 00 78 27 "
                "10 00 00 78 4a 38 00 00 78 00 00 00 00 00"
            ),
        )

    def test_custom_report_encodes_confirmed_first_band_gain(self):
        report = microphone_eq.build_report([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(report[12:14], bytes.fromhex("00 8c"))
        self.assertEqual(report[17:19], bytes.fromhex("00 78"))

    def test_builtin_presets_use_correct_eq_template_not_noise_gate(self):
        for name in microphone_eq.PRESETS:
            with self.subTest(name=name), patch.object(microphone_eq, "send_hid_report") as send:
                microphone_eq.apply_preset(name)
                report, prefix = send.call_args.args
                self.assertEqual(report[:8], bytes.fromhex("02 0c 38 00 0d 2d 00 03"))
                self.assertEqual(
                    [report[11 + 5 * index] for index in range(10)],
                    [0x16 if name == "Standard" else 0] * 10,
                )
                self.assertEqual(
                    [int.from_bytes(report[offset:offset + 2], "big") for offset in microphone_eq.GAIN_OFFSETS],
                    [120 + round(gain * 20) for gain in microphone_eq.PRESETS[name]],
                )
                self.assertEqual(prefix, microphone_eq.MIC_PROFILE_RESPONSE_PREFIX)
                send.assert_called_once()

    def test_custom_apply_uses_mic_report_and_ack_prefix(self):
        with (
            patch.object(microphone_eq, "load_presets", return_value={"My mic": [1] * 10}),
            patch.object(microphone_eq, "send_hid_report") as send,
        ):
            microphone_eq.apply_preset("My mic")
        send.assert_called_once_with(
            microphone_eq.build_report([1] * 10),
            microphone_eq.MIC_PROFILE_RESPONSE_PREFIX,
        )

    def test_rejects_out_of_range_and_non_half_db_values(self):
        for gains in (
            [6.5] + [0] * 9,
            [-6.5] + [0] * 9,
            [0.25] + [0] * 9,
            [True] + [0] * 9,
        ):
            with self.subTest(gains=gains), self.assertRaises(ValueError):
                microphone_eq.build_report(gains)

    def test_custom_presets_use_separate_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                gains = [0.5] + [0] * 9
                microphone_eq.save_preset("My mic", gains)
                self.assertEqual(
                    microphone_eq.load_presets()["My mic"], gains
                )
                self.assertTrue(
                    microphone_eq.config_path().name
                    == "microphone-eq-presets.json"
                )
                self.assertEqual(
                    json.loads(microphone_eq.config_path().read_text()),
                    {"My mic": gains},
                )
                microphone_eq.delete_preset("My mic")
                self.assertNotIn("My mic", microphone_eq.load_presets())
                self.assertIn("Standard", microphone_eq.load_presets())

    def test_factory_names_cannot_be_saved_as_custom_presets(self):
        for name in microphone_eq.PRESETS:
            with self.subTest(name=name), self.assertRaises(ValueError):
                microphone_eq.save_preset(name, [0] * 10)


if __name__ == "__main__":
    unittest.main()
