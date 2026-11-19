import fcntl
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_battery.py"
spec = importlib.util.spec_from_file_location("a50_battery", SCRIPT)
assert spec and spec.loader
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)


def report(values: str) -> bytes:
    return bytes.fromhex("02 0c 06 00 06 0a " + values) + bytes(55)


class BatteryTest(unittest.TestCase):
    def test_decodes_captured_states(self):
        self.assertEqual(battery.decode_battery(report("63 64 00")), (99, 100, False))
        self.assertEqual(battery.decode_battery(report("64 5f 01")), (100, 95, True))

    def test_rejects_invalid_reports(self):
        for value in (report("65 5f 01"), report("64 5f 02"), b"\x02"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                battery.decode_battery(value)

    def test_sends_only_the_observed_request_and_ignores_unrelated_events(self):
        boom = bytes.fromhex("02 0c 07 00 0c 00 00 00 00 0a") + bytes(54)
        with tempfile.TemporaryDirectory() as runtime:
            with (
                patch.dict(battery.os.environ, {"XDG_RUNTIME_DIR": runtime}),
                patch.object(battery.os, "open", return_value=42),
                patch.object(battery.os, "write", return_value=64) as write,
                patch.object(battery.os, "read", side_effect=[boom, report("64 5f 01")]),
                patch.object(battery.os, "close") as close,
                patch.object(battery.select, "select", return_value=([42], [], [])),
            ):
                self.assertEqual(battery.read_battery(), (100, 95, True))
                write.assert_called_once_with(42, bytes.fromhex("02 0c 03 00 06 0a") + bytes(58))
                close.assert_called_once_with(42)

    def test_busy_shared_lock_is_reported_without_opening_device(self):
        with tempfile.TemporaryDirectory() as runtime:
            with (Path(runtime) / "a50-hid.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                errors = io.StringIO()
                with (
                    patch.dict(battery.os.environ, {"XDG_RUNTIME_DIR": runtime}),
                    patch.object(battery.os, "open") as device_open,
                    patch("sys.argv", ["a50-battery", "--json"]),
                    patch("sys.stderr", errors),
                    patch("sys.stdout", new_callable=io.StringIO) as output,
                ):
                    self.assertEqual(battery.main(), 1)
                    device_open.assert_not_called()
                    self.assertIn("A50 battery read failed", errors.getvalue())
                    self.assertEqual(output.getvalue(), "")

    def test_lock_is_held_during_request_and_released_after_response(self):
        with tempfile.TemporaryDirectory() as runtime:
            lock_path = Path(runtime) / "a50-hid.lock"

            def write_request(_fd, _request):
                with lock_path.open("a") as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return 64

            with (
                patch.dict(battery.os.environ, {"XDG_RUNTIME_DIR": runtime}),
                patch.object(battery.os, "open", return_value=42),
                patch.object(battery.os, "write", side_effect=write_request),
                patch.object(battery.os, "read", return_value=report("64 5f 01")),
                patch.object(battery.os, "close"),
                patch.object(battery.select, "select", return_value=([42], [], [])),
            ):
                self.assertEqual(battery.read_battery(), (100, 95, True))
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_missing_runtime_directory_is_reported(self):
        errors = io.StringIO()
        with (
            patch.dict(battery.os.environ, {"XDG_RUNTIME_DIR": ""}),
            patch.object(battery.os, "open") as device_open,
            patch("sys.argv", ["a50-battery"]),
            patch("sys.stderr", errors),
        ):
            self.assertEqual(battery.main(), 1)
            device_open.assert_not_called()
        self.assertIn("XDG_RUNTIME_DIR is not set", errors.getvalue())

    def test_json_output_for_panel(self):
        output = io.StringIO()
        with (
            patch.object(battery, "read_battery", return_value=(100, 95, True)),
            patch("sys.argv", ["a50-battery", "--json"]),
            patch("sys.stdout", output),
        ):
            self.assertEqual(battery.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {
            "level": 95,
            "charging": True,
            "reported_values": [100, 95],
            "experimental": True,
        })

    def test_default_terminal_output_remains_readable(self):
        output = io.StringIO()
        with (
            patch.object(battery, "read_battery", return_value=(99, 100, False)),
            patch("sys.argv", ["a50-battery"]),
            patch("sys.stdout", output),
        ):
            self.assertEqual(battery.main(), 0)
        self.assertIn("Battery (experimental): 99%", output.getvalue())

    def test_errors_are_reported_without_success_output(self):
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch.object(battery, "read_battery", side_effect=TimeoutError("no response")),
            patch("sys.argv", ["a50-battery", "--json"]),
            patch("sys.stdout", output),
            patch("sys.stderr", errors),
        ):
            self.assertEqual(battery.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("no response", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
