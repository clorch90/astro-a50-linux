import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_device_status.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("a50_device_status", SCRIPT)
assert spec and spec.loader
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


def report(hex_bytes):
    data = bytes.fromhex(hex_bytes)
    return data + bytes(64 - len(data))


class DeviceStatusTest(unittest.TestCase):
    def test_decodes_captured_basic_settings(self):
        examples = (
            ("sleep", "02 0c 05 00 07 0e 3c 0f", 15),
            ("sidetone", "02 0c 07 00 09 0e 01 01 ff 00", 0),
            ("brightness", "02 0c 04 00 0f 0e 64", 100),
            ("sound", "02 0c 04 00 10 0e 01", 1),
            ("noise-gate", "02 0c 04 00 14 1e 02", 2),
        )
        for name, response, expected in examples:
            with self.subTest(name=name):
                with patch.object(status, "exchange_hid_report", return_value=report(response)) as exchange:
                    self.assertEqual(status.read_setting(name), expected)
                request, prefix = status.REQUESTS[name]
                exchange.assert_called_once_with(report(request), bytes.fromhex(prefix))

    def test_decodes_output_and_microphone_curves(self):
        output = report(
            "02 0c 36 00 0d 1e 00 00 14 16 00 a0 00 32 16 00 64 "
            "00 7d 16 00 78 00 fa 16 00 82 01 f4 16 00 78 03 e8 16 "
            "00 6e 09 c4 16 00 78 13 88 16 00 96 27 10 16 00 78 "
            "4e 20 16 00 50"
        )
        microphone = report(
            "02 0c 36 00 0d 1e 00 00 50 00 00 78 00 96 00 00 78 "
            "00 fa 00 00 78 01 90 00 00 78 03 20 00 00 78 05 dc 00 "
            "00 78 09 c4 00 00 78 13 88 00 00 78 27 10 00 00 78 "
            "4a 38 00 00 78"
        )
        self.assertEqual(
            status.decode_setting("output-eq", output),
            [2, -1, 0, 0.5, 0, -0.5, 0, 1.5, 0, -2],
        )
        self.assertEqual(status.decode_setting("microphone-eq", microphone), [0] * 10)
        with self.assertRaisesRegex(ValueError, "band frequency"):
            status.decode_setting("output-eq", microphone)
        invalid_gain = bytearray(output)
        invalid_gain[11] = 161
        with self.assertRaisesRegex(ValueError, "gain"):
            status.decode_setting("output-eq", bytes(invalid_gain))

    def test_rejects_malformed_and_unsupported_readbacks(self):
        for name, response in (
            ("sidetone", report("02 0c 07 00 09 0e 01 01 ff 07")),
            ("brightness", report("02 0c 04 00 0f 0e 65")),
            ("sleep", report("02 0c 05 00 07 0e 3c 02")),
            ("sound", report("02 0c 04 00 10 0e 03")),
            ("noise-gate", report("02 0c 04 00 14 1e 03")),
            ("sound", bytes(64)),
            ("sound", bytes(6)),
        ):
            with self.subTest(name=name, response=response[:10]), self.assertRaises(ValueError):
                status.decode_setting(name, response)

    def test_device_errors_are_reported_by_cli(self):
        with (
            patch.object(status, "read_setting", side_effect=OSError("Device unavailable")),
            patch("sys.argv", ["a50-device-status", "sound"]),
            patch("sys.stderr") as stderr,
        ):
            self.assertEqual(status.main(), 1)
            self.assertIn("Device unavailable", "".join(call.args[0] for call in stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
