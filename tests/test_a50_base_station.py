import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_base_station.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("a50_base_station", SCRIPT)
assert spec and spec.loader
base_station = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_station)


class BaseStationTest(unittest.TestCase):
    def test_build_brightness_report_matches_capture(self):
        for level in (0, 50, 100):
            with self.subTest(level=level):
                self.assertEqual(
                    base_station.build_brightness_report(level),
                    bytes.fromhex("02 0c 04 00 0f 1d")
                    + bytes((level,))
                    + bytes(57),
                )

    def test_brightness_rejects_out_of_range_and_boolean_values(self):
        for level in (-1, 101, True, 50.0):
            with self.subTest(level=level), self.assertRaises(ValueError):
                base_station.build_brightness_report(level)

    def test_sleep_reports_match_all_captured_timeouts(self):
        expected = {"off": 0, "15": 15, "30": 30, "60": 60}
        for minutes, value in expected.items():
            with self.subTest(minutes=minutes):
                self.assertEqual(
                    base_station.build_sleep_report(minutes),
                    bytes.fromhex("02 0c 05 00 07 1d 3c")
                    + bytes((value,))
                    + bytes(56),
                )

    def test_sound_reports_match_captured_modes(self):
        expected = {"all": 1, "minimal": 2, "off": 0}
        for mode, value in expected.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    base_station.build_sound_report(mode),
                    bytes.fromhex("02 0c 04 00 10 1d")
                    + bytes((value, 0))
                    + bytes(56),
                )

    def test_setting_commands_use_captured_acknowledgements(self):
        with patch.object(base_station, "send_hid_report") as send:
            base_station.set_brightness(50)
            base_station.set_sleep_timeout("15")
            base_station.set_sound_mode("minimal")
        self.assertEqual(
            send.call_args_list[0].args,
            (base_station.build_brightness_report(50), base_station.BRIGHTNESS_RESPONSE),
        )
        self.assertEqual(
            send.call_args_list[1].args,
            (base_station.build_sleep_report("15"), base_station.SLEEP_RESPONSE),
        )
        self.assertEqual(
            send.call_args_list[2].args,
            (base_station.build_sound_report("minimal"), base_station.SOUND_RESPONSE),
        )

    def test_connected_bluetooth_response_reads_device_name(self):
        name = "Test device"
        name_payload = (
            bytes.fromhex("02 0c 1c 00 0e 2d 30")
            + bytes((len(name.encode("utf-8")),))
            + name.encode("utf-8")
        )
        name_response = name_payload + bytes(64 - len(name_payload))
        status_response = bytes.fromhex("02 0c 04 00 0e 0d 01 00") + bytes(56)
        with patch.object(
            base_station,
            "exchange_hid_report",
            side_effect=(status_response, name_response),
        ) as exchange:
            self.assertEqual(
                base_station.read_bluetooth_status(),
                {"connected": True, "device_name": name},
            )
        self.assertEqual(exchange.call_count, 2)
        self.assertTrue(exchange.call_args_list[0].args[0].startswith(
            bytes.fromhex("02 0c 03 00 0e 0d")
        ))
        self.assertEqual(exchange.call_args_list[1].args[1], base_station.BLUETOOTH_NAME_RESPONSE)

    def test_disconnected_bluetooth_does_not_query_device_name(self):
        status_response = bytes.fromhex("02 0c 04 00 0e 0d 00 00") + bytes(56)
        with patch.object(
            base_station, "exchange_hid_report", return_value=status_response
        ) as exchange:
            self.assertEqual(
                base_station.read_bluetooth_status(),
                {"connected": False, "device_name": None},
            )
        exchange.assert_called_once()

    def test_invalid_bluetooth_state_is_rejected(self):
        status_response = bytes.fromhex("02 0c 04 00 0e 0d 02 00") + bytes(56)
        with (
            patch.object(
                base_station, "exchange_hid_report", return_value=status_response
            ),
            self.assertRaisesRegex(ValueError, "Unexpected Bluetooth connection state"),
        ):
            base_station.read_bluetooth_status()

    def test_list_cli_reports_captured_choices(self):
        with (
            patch("sys.argv", ["a50-base-station", "list"]),
            patch("sys.stdout") as stdout,
        ):
            self.assertEqual(base_station.main(), 0)
        output = "".join(call.args[0] for call in stdout.write.call_args_list)
        result = json.loads(output)
        self.assertEqual(result["sleep_minutes"], [0, 15, 30, 60])
        self.assertEqual(result["sound_modes"], {"all": 1, "minimal": 2, "off": 0})


if __name__ == "__main__":
    unittest.main()
