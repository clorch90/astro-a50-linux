#!/usr/bin/env python3
import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from a50_equalizer import send_hid_report


MIC_PROFILE_TEMPLATE = bytes.fromhex(
    "02 0c 38 00 0d 2d 00 03 00 00 "
    "50 00 00 78 00 96 00 00 78 00 fa 00 00 78 01 90 00 00 78 03 "
    "20 00 00 78 05 dc 00 00 78 09 c4 00 00 78 13 88 00 00 78 27 "
    "10 00 00 78 4a 38 00 00 78 00 00 00 00 00"
)
FACTORY_MIC_PROFILE_TEMPLATE = bytes.fromhex(
    "02 0c 38 00 0d 2d 00 03 00 00 "
    "50 16 00 78 00 96 16 00 78 00 fa 16 00 78 01 90 16 00 78 03 "
    "20 16 00 78 05 dc 16 00 78 09 c4 16 00 78 13 88 16 00 78 27 "
    "10 16 00 78 4a 38 16 00 78 00 00 00 00 00"
)
BAND_COUNT = 10
MIN_GAIN_DB = -6
MAX_GAIN_DB = 6
GAIN_OFFSETS = tuple(12 + 5 * index for index in range(BAND_COUNT))
GAIN_ZERO = 0x78
GAIN_UNITS_PER_DB = 20
MIC_PROFILE_RESPONSE_PREFIX = bytes.fromhex("02 0c 03 00 0d 2d")
PRESETS = {
    "Standard": [0] * BAND_COUNT,
    "Warm": [0, 1, 1, 0.5, 0, 0, -0.5, -1, -1, -1],
    "Klar": [-2, -1.5, -1, -0.5, 0, 1, 1.5, 1.5, 1, 0],
}


def validate_gains(gains: list[int | float]) -> list[int | float]:
    if not isinstance(gains, list) or len(gains) != BAND_COUNT:
        raise ValueError(f"Exactly {BAND_COUNT} microphone EQ gains are required")
    normalized = []
    for gain in gains:
        if (
            isinstance(gain, bool)
            or not isinstance(gain, (int, float))
            or not math.isfinite(gain)
            or not MIN_GAIN_DB <= gain <= MAX_GAIN_DB
            or not math.isclose(gain * 2, round(gain * 2), abs_tol=1e-9)
        ):
            raise ValueError(
                f"Each microphone EQ gain must be a 0.5 dB step from "
                f"{MIN_GAIN_DB} to {MAX_GAIN_DB} dB"
            )
        value = round(gain * 2) / 2
        normalized.append(int(value) if value.is_integer() else value)
    return normalized


def build_report(
    gains: list[int | float], template: bytes = MIC_PROFILE_TEMPLATE
) -> bytes:
    gains = validate_gains(gains)
    if len(template) != 64:
        raise ValueError("Microphone EQ template must contain exactly 64 bytes")
    report = bytearray(template)
    for offset, gain in zip(GAIN_OFFSETS, gains):
        value = GAIN_ZERO + round(GAIN_UNITS_PER_DB * gain)
        report[offset:offset + 2] = value.to_bytes(2, "big")
    return bytes(report)


def config_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "astro-a50-linux" / "microphone-eq-presets.json"


def load_presets() -> dict[str, list[int | float]]:
    presets = {name: gains.copy() for name, gains in PRESETS.items()}
    path = config_path()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return presets
    if not isinstance(saved, dict):
        raise ValueError("Saved microphone EQ presets must be a JSON object")
    for name, gains in saved.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 40
            or name in PRESETS
        ):
            raise ValueError("Saved microphone EQ preset has an invalid or reserved name")
        presets[name] = validate_gains(gains)
    return presets


def save_preset(name: str, gains: list[int | float]) -> None:
    name = name.strip()
    if not name or len(name) > 40 or name in PRESETS:
        raise ValueError("Choose a non-empty custom preset name of at most 40 characters")
    gains = validate_gains(gains)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = {}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("Saved microphone EQ presets must be a JSON object")
    saved[name] = gains
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(saved, temporary, indent=2)
            temporary.write("\n")
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def delete_preset(name: str) -> None:
    if name in PRESETS:
        raise ValueError("Built-in microphone EQ presets cannot be deleted")
    path = config_path()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"No saved preset named {name!r}") from error
    if not isinstance(saved, dict) or name not in saved:
        raise ValueError(f"No saved preset named {name!r}")
    del saved[name]
    path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")


def apply_preset(name: str) -> None:
    presets = load_presets()
    if name not in presets:
        raise ValueError(f"No microphone EQ preset named {name!r}")
    template = FACTORY_MIC_PROFILE_TEMPLATE if name == "Standard" else MIC_PROFILE_TEMPLATE
    send_hid_report(build_report(presets[name], template), MIC_PROFILE_RESPONSE_PREFIX)


def apply_values(gains: list[int | float]) -> None:
    send_hid_report(build_report(gains), MIC_PROFILE_RESPONSE_PREFIX)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage the experimental A50 microphone equalizer"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", help="List built-in and saved microphone EQ presets")
    apply_parser = subparsers.add_parser("apply", help="Apply a named microphone preset")
    apply_parser.add_argument("name")
    values_parser = subparsers.add_parser(
        "apply-values", help="Apply ten microphone band gains in dB"
    )
    values_parser.add_argument("gains", type=float, nargs=BAND_COUNT)
    save_parser = subparsers.add_parser("save", help="Save a custom microphone EQ preset")
    save_parser.add_argument("name")
    save_parser.add_argument("gains", type=float, nargs=BAND_COUNT)
    delete_parser = subparsers.add_parser(
        "delete", help="Delete a saved custom microphone preset"
    )
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
            apply_preset(args.name)
        else:
            apply_values(args.gains)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 microphone equalizer failed: {error}", file=sys.stderr)
        return 1
    if args.action in ("save", "delete"):
        print(
            f"Preset {args.name!r} saved"
            if args.action == "save"
            else f"Preset {args.name!r} deleted"
        )
    elif args.action in ("apply", "apply-values"):
        print("Microphone EQ profile accepted; the current profile was not read back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
