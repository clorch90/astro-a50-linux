import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup.sh"


@unittest.skipIf(os.geteuid() == 0, "Setup must run as a normal user")
class SetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home with spaces"
        self.home.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "commands"
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "SETUP_TEST_LOG": str(self.log),
        })
        self.stub("systemctl", 'printf "systemctl %s\\n" "$*" >> "$SETUP_TEST_LOG"')
        for name in ("wpctl", "pw-dump", "pw-link", "paplay"):
            self.stub(name, "exit 0")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/bin/bash\nset -eu\n{body}\n")
        path.chmod(0o755)

    def run_setup(self, answers):
        return subprocess.run(
            ["bash", str(SETUP)],
            input="\n".join(answers) + "\n",
            text=True,
            capture_output=True,
            env=self.env,
            timeout=15,
        )

    def commands(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_selecting_nothing_does_not_change_home(self):
        result = self.run_setup(["n"] * 6)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.commands(), "")

    def test_prompts_are_english_for_german_locale(self):
        self.env.pop("LC_ALL")
        self.env.pop("LC_MESSAGES", None)
        self.env["LANG"] = "de_DE.UTF-8"
        result = self.run_setup(["n"] * 6)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Install the desktop app?", result.stdout)
        self.assertIn("Nothing selected; no changes made.", result.stdout)

    def test_boom_service_installs_sounds_and_starts_only_after_confirmation(self):
        result = self.run_setup(["n", "n", "n", "y", "n", "n", "n", "y"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.home / ".config/systemd/user/a50-flip-mute.service").read_bytes(),
            (ROOT / "systemd/a50-flip-mute.service").read_bytes(),
        )
        self.assertTrue((self.home / ".local/share/toggle-mic-mute-sounds/mute.wav").is_file())
        self.assertIn("systemctl --user enable a50-flip-mute.service", self.commands())
        self.assertIn("systemctl --user restart a50-flip-mute.service", self.commands())

    def test_declining_overwrite_preserves_files_and_does_not_restart(self):
        target = self.home / ".config/wireplumber/wireplumber.conf.d/51-a50-labels.conf"
        target.parent.mkdir(parents=True)
        target.write_text("custom configuration\n")
        result = self.run_setup(["y", "n", "n", "n", "n", "n", "n"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "custom configuration\n")
        self.assertNotIn("restart", self.commands())

    def test_extension_installs_its_helpers_without_gui(self):
        self.stub("gnome-shell", 'echo "GNOME Shell 50.1"')
        self.stub("gnome-extensions", """
printf 'gnome-extensions %s\\n' "$*" >> "$SETUP_TEST_LOG"
case "$1" in
  info) exit 1 ;;
  pack) shift; while [ "$1" != "--out-dir" ]; do shift; done
        touch "$2/a50-battery@astro-a50-linux.shell-extension.zip" ;;
esac
""")
        result = self.run_setup(["n", "n", "n", "n", "n", "y", "n", "y"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("a50-battery", "a50-sidetone", "a50-equalizer", "a50_equalizer.py", "a50-base-station"):
            self.assertTrue((self.home / ".local/bin" / name).is_file(), name)
        self.assertFalse((self.home / ".local/bin/a50-control").exists())
        self.assertIn("gnome-extensions enable a50-battery@astro-a50-linux", self.commands())

    def test_gui_installs_helpers_and_sounds_without_starting_services(self):
        bindings = subprocess.run(
            ["/usr/bin/python3", "-c", 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")'],
            capture_output=True,
        )
        if bindings.returncode:
            self.skipTest("GTK and Libadwaita bindings unavailable")
        result = self.run_setup(["n", "n", "n", "n", "y", "n", "n", "y"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".local/bin/a50-control").is_file())
        self.assertTrue((self.home / ".local/bin/a50-device-status").is_file())
        self.assertTrue((self.home / ".local/bin/a50-battery").is_file())
        self.assertTrue((self.home / ".local/share/toggle-mic-mute-sounds/unmute.wav").is_file())
        self.assertEqual(self.commands(), "")

    @unittest.skipIf(Path("/etc/udev/rules.d/70-astro-a50-hidraw.rules").exists(), "Host already has an A50 udev rule")
    def test_udev_requires_confirmation_and_invokes_only_mocked_sudo(self):
        self.stub("sudo", 'printf "sudo %s\\n" "$*" >> "$SETUP_TEST_LOG"')
        self.stub("udevadm", "exit 0")
        result = self.run_setup(["n", "n", "n", "y", "n", "n", "y", "y"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("70-astro-a50-hidraw.rules", self.commands())
        self.assertIn("sudo udevadm control --reload-rules", self.commands())

    def test_service_failure_is_reported_as_potentially_partial(self):
        self.stub("systemctl", """
case "$*" in *restart*) exit 1 ;; esac
exit 0
""")
        result = self.run_setup(["y", "n", "n", "n", "n", "n", "y"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("some changes may already have been made", result.stderr)

    def test_eof_does_not_apply_partial_selection(self):
        result = self.run_setup(["y"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.commands(), "")


if __name__ == "__main__":
    unittest.main()
