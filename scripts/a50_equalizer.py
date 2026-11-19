#!/usr/bin/env python3
import argparse
import fcntl
import json
import math
import os
import select
import sys
import tempfile
import time
from pathlib import Path


DEVICE = "/dev/input/by-id/usb-Logitech_A50-if08-hidraw"
RESPONSE_PREFIX = bytes.fromhex("02 0c 03 00 0d 2d")
PROFILE_TEMPLATE = bytes.fromhex(
    "02 0c 38 00 0d 2d 01 03 00 00 "
    "14 00 00 78 00 32 00 00 78 00 7d 00 00 78 00 fa 00 00 78 01 "
    "f4 00 00 78 03 e8 00 00 78 09 c4 00 00 78 13 88 00 00 78 27 "
    "10 00 00 78 4e 20 00 00 78 00 00 00 00 00"
)
FACTORY_PROFILE_TEMPLATE = bytes.fromhex(
    "02 0c 38 00 0d 2d 01 03 00 00 "
    "14 16 00 78 00 32 16 00 78 00 7d 16 00 78 00 fa 16 00 78 01 "
    "f4 16 00 78 03 e8 16 00 78 09 c4 16 00 78 13 88 16 00 78 27 "
    "10 16 00 78 4e 20 16 00 78 00 00 00 00 00"
)
BAND_COUNT = 10
MIN_GAIN_DB = -6
MAX_GAIN_DB = 6
GAIN_OFFSETS = tuple(12 + 5 * index for index in range(BAND_COUNT))
GAIN_ZERO = 0x78
GAIN_UNITS_PER_DB = 20
FACTORY_PRESET_NAMES = ("Standard",)
PRESETS = {
    "Standard": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass": [3, 3, 2, 1, 0, 0, 0, 0, 0, 0],
    "Voice": [-2, -1, 0, 1, 2, 2, 1, 0, -1, -2],
    "Footsteps": [-2, -1, 0, 2, 3, 3, 2, 1, 0, -1],
}


def validate_gains(gains: list[int | float]) -> list[int | float]:
    if not isinstance(gains, list) or len(gains) != BAND_COUNT:
        raise ValueError(f"Exactly {BAND_COUNT} EQ gains are required")
    normalized = []
    for gain in gains:
        if (
            isinstance(gain, bool)
            or not isinstance(gain, (int, float))
            or not MIN_GAIN_DB <= gain <= MAX_GAIN_DB
            or not math.isfinite(gain)
            or not math.isclose(gain * 2, round(gain * 2), abs_tol=1e-9)
        ):
            raise ValueError(
                f"Each EQ gain must be a 0.5 dB step from {MIN_GAIN_DB} to {MAX_GAIN_DB} dB"
            )
        value = round(gain * 2) / 2
        normalized.append(int(value) if value.is_integer() else value)
    return normalized


def build_report(
    gains: list[int | float], template: bytes = PROFILE_TEMPLATE
) -> bytes:
    gains = validate_gains(gains)
    if len(template) != 64:
        raise ValueError("EQ report template must contain exactly 64 bytes")
    report = bytearray(template)
    for offset, gain in zip(GAIN_OFFSETS, gains):
        value = GAIN_ZERO + round(GAIN_UNITS_PER_DB * gain)
        report[offset:offset + 2] = value.to_bytes(2, "big")
    return bytes(report)


def config_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "astro-a50-linux" / "eq-presets.json"


def load_presets() -> dict[str, list[int | float]]:
    presets = {name: gains.copy() for name, gains in PRESETS.items()}
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return presets
    if not isinstance(raw, dict):
        raise ValueError("Saved EQ presets must be a JSON object")
    for name, gains in raw.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 40
            or name in PRESETS
        ):
            raise ValueError("Saved EQ preset has an invalid or reserved name")
        presets[name] = validate_gains(gains)
    return presets


def save_preset(name: str, gains: list[int | float]) -> None:
    name = name.strip()
    if not name or len(name) > 40 or name in PRESETS:
        raise ValueError("Choose a non-empty custom preset name of at most 40 characters")
    gains = validate_gains(gains)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    custom = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Saved EQ presets must be a JSON object")
        custom = raw
    custom[name] = gains
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(custom, temporary, indent=2)
            temporary.write("\n")
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def delete_preset(name: str) -> None:
    if name in PRESETS:
        raise ValueError("Built-in EQ presets cannot be deleted")
    path = config_path()
    try:
        custom = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"No saved preset named {name!r}") from error
    if not isinstance(custom, dict) or name not in custom:
        raise ValueError(f"No saved preset named {name!r}")
    del custom[name]
    path.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")


def exchange_hid_report(report: bytes, response_prefix: bytes) -> bytes:
    if len(report) != 64:
        raise ValueError("A50 HID report must contain exactly 64 bytes")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    lock_path = Path(runtime) / "a50-hid.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(DEVICE, os.O_RDWR | os.O_NONBLOCK)
        try:
            written = os.write(fd, report)
            if written != len(report):
                raise OSError(f"Incomplete A50 HID request: {written}/{len(report)} bytes")
            deadline = time.monotonic() + 4
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise TimeoutError("Timed out waiting for the A50 HID response")
                response = os.read(fd, 64)
                if not response:
                    raise OSError("A50 HID device disconnected")
                if response.startswith(response_prefix):
                    if len(response) != 64:
                        raise ValueError("Unexpected A50 HID response length")
                    return response
        finally:
            os.close(fd)


def send_hid_report(
    report: bytes,
    response_prefix: bytes = RESPONSE_PREFIX,
    response_status: int = 0,
) -> None:
    response = exchange_hid_report(report, response_prefix)
    if response[6] != response_status:
        raise ValueError("Unexpected A50 HID response status")


def set_equalizer(
    gains: list[int | float], template: bytes = PROFILE_TEMPLATE
) -> None:
    send_hid_report(build_report(gains, template))


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the experimental A50 headset EQ")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", help="List built-in and saved presets")
    apply_parser = subparsers.add_parser("apply", help="Apply a named preset")
    apply_parser.add_argument("name")
    values_parser = subparsers.add_parser("apply-values", help="Apply ten band gains in dB")
    values_parser.add_argument("gains", type=float, nargs=BAND_COUNT)
    save_parser = subparsers.add_parser("save", help="Save a custom preset")
    save_parser.add_argument("name")
    save_parser.add_argument("gains", type=float, nargs=BAND_COUNT)
    delete_parser = subparsers.add_parser("delete", help="Delete a saved custom preset")
    delete_parser.add_argument("name")
    args = parser.parse_args()

    try:
        if args.action == "list":
            print(json.dumps(load_presets()))
        elif args.action == "delete":
            delete_preset(args.name)
        elif args.action == "save":
            save_preset(args.name, args.gains)
        elif args.action == "apply":
            presets = load_presets()
            if args.name not in presets:
                raise ValueError(f"No EQ preset named {args.name!r}")
            template = (
                FACTORY_PROFILE_TEMPLATE
                if args.name in FACTORY_PRESET_NAMES
                else PROFILE_TEMPLATE
            )
            set_equalizer(presets[args.name], template)
        else:
            set_equalizer(args.gains)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 equalizer failed: {error}", file=sys.stderr)
        return 1
    if args.action in ("save", "delete"):
        print(f"Preset {args.name!r} saved" if args.action == "save" else f"Preset {args.name!r} deleted")
    elif args.action in ("apply", "apply-values"):
        print("EQ profile accepted; the current profile was not read back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
