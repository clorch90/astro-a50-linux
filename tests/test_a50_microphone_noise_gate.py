import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "a50_microphone_noise_gate.py"
)
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("a50_microphone_noise_gate", SCRIPT)
assert spec and spec.loader
noise_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noise_gate)


class MicrophoneNoiseGateTest(unittest.TestCase):
    def test_build_report_matches_all_captured_states(self):
        for state, state_id in noise_gate.NOISE_GATE_STATES.items():
            with self.subTest(state=state):
                self.assertEqual(
                    noise_gate.build_report(state),
                    bytes.fromhex("02 0c 04 00 14 2e")
                    + bytes((state_id, 0))
                    + bytes(56),
                )

    def test_state_ids_match_the_confirmed_capture_order(self):
        self.assertEqual(
            noise_gate.NOISE_GATE_STATES,
            {"Aus": 0, "Nacht": 2, "Zu Hause": 1, "Turnier": 4},
        )

    def test_apply_state_uses_captured_echo_and_status(self):
        with patch.object(noise_gate, "send_hid_report") as send:
            noise_gate.apply_state("Zu Hause")
        send.assert_called_once_with(
            noise_gate.build_report("Zu Hause"),
            noise_gate.RESPONSE_PREFIX + bytes((1,)),
            response_status=1,
        )

    def test_unknown_state_is_rejected_without_sending(self):
        with (
            patch.object(noise_gate, "send_hid_report") as send,
            self.assertRaises(ValueError),
        ):
            noise_gate.apply_state("Invalid")
        send.assert_not_called()

    def test_list_cli_reports_captured_states(self):
        with (
            patch("sys.argv", ["a50-microphone-noise-gate", "list"]),
            patch("sys.stdout") as stdout,
        ):
            self.assertEqual(noise_gate.main(), 0)
        self.assertEqual(
            json.loads("".join(call.args[0] for call in stdout.write.call_args_list)),
            noise_gate.NOISE_GATE_STATES,
        )

    def test_device_failure_is_reported_by_cli(self):
        with (
            patch.object(
                noise_gate,
                "apply_state",
                side_effect=OSError("device unavailable"),
            ),
            patch(
                "sys.argv",
                ["a50-microphone-noise-gate", "set", "Aus"],
            ),
            patch("sys.stderr") as stderr,
        ):
            self.assertEqual(noise_gate.main(), 1)
            self.assertIn(
                "device unavailable",
                "".join(call.args[0] for call in stderr.write.call_args_list),
            )

    def test_cli_reports_acknowledgement_without_claiming_readback(self):
        with (
            patch.object(noise_gate, "apply_state"),
            patch("sys.argv", ["a50-microphone-noise-gate", "set", "Nacht"]),
            patch("sys.stdout") as stdout,
        ):
            self.assertEqual(noise_gate.main(), 0)
        output = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("command for 'Nacht' acknowledged", output)
        self.assertIn("was not read back", output)


if __name__ == "__main__":
    unittest.main()
