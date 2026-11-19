import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_sidetone.py"
spec = importlib.util.spec_from_file_location("a50_sidetone", SCRIPT)
assert spec and spec.loader
sidetone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidetone)


class SidetoneTest(unittest.TestCase):
    def test_valid_request_ignores_unrelated_reports(self):
        response = sidetone.RESPONSE_PREFIX + bytes(58)
        with (
            patch.dict(sidetone.os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}),
            patch.object(Path, "open", autospec=True) as lock,
            patch.object(sidetone.fcntl, "flock"),
            patch.object(sidetone.os, "open", return_value=42),
            patch.object(sidetone.os, "write", return_value=64) as write,
            patch.object(sidetone.os, "read", side_effect=[bytes(64), response]),
            patch.object(sidetone.os, "close") as close,
            patch.object(sidetone.select, "select", return_value=([42], [], [])),
        ):
            sidetone.set_sidetone(2)
        lock.assert_called_once()
        self.assertEqual(str(lock.call_args.args[0]), "/run/user/1000/a50-hid.lock")
        write.assert_called_once_with(42, bytes.fromhex("02 0c 06 00 09 1d 01 ff 02") + bytes(55))
        close.assert_called_once_with(42)

    def test_invalid_level_is_rejected_before_opening_device(self):
        with patch.object(sidetone.os, "open") as device_open:
            for value in (-1, 7, True, 2.5):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    sidetone.set_sidetone(value)
        device_open.assert_not_called()

    def test_rejects_error_response(self):
        response = sidetone.RESPONSE_PREFIX + bytes([1]) + bytes(57)
        with (
            patch.dict(sidetone.os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}),
            patch.object(Path, "open"),
            patch.object(sidetone.fcntl, "flock"),
            patch.object(sidetone.os, "open", return_value=42),
            patch.object(sidetone.os, "write", return_value=64),
            patch.object(sidetone.os, "read", return_value=response),
            patch.object(sidetone.os, "close") as close,
            patch.object(sidetone.select, "select", return_value=([42], [], [])),
            self.assertRaises(ValueError),
        ):
            sidetone.set_sidetone(6)
        close.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
