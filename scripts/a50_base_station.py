#!/usr/bin/env python3
import argparse
import json
import sys

from a50_equalizer import exchange_hid_report, send_hid_report


SLEEP_MINUTES = {"off": 0, "15": 15, "30": 30, "60": 60}
SOUND_MODE_IDS = {"all": 1, "minimal": 2, "off": 0}
BRIGHTNESS_RESPONSE = bytes.fromhex("02 0c 03 00 0f 1d")
SLEEP_RESPONSE = bytes.fromhex("02 0c 03 00 07 1d")
SOUND_RESPONSE = bytes.fromhex("02 0c 03 00 10 1d")
BLUETOOTH_STATUS_RESPONSE = bytes.fromhex("02 0c 04 00 0e 0d")
BLUETOOTH_NAME_RESPONSE = bytes.fromhex("02 0c 1c 00 0e 2d")


def build_brightness_report(level: int) -> bytes:
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100:
        raise ValueError("Brightness must be an integer from 0 to 100")
    return bytes.fromhex("02 0c 04 00 0f 1d") + bytes((level,)) + bytes(57)


def build_sleep_report(minutes: str) -> bytes:
    try:
        value = SLEEP_MINUTES[minutes]
    except KeyError as error:
        raise ValueError(f"Unsupported sleep timeout: {minutes!r}") from error
    return bytes.fromhex("02 0c 05 00 07 1d 3c") + bytes((value,)) + bytes(56)


def build_sound_report(mode: str) -> bytes:
    try:
        value = SOUND_MODE_IDS[mode]
    except KeyError as error:
        raise ValueError(f"Unsupported sound mode: {mode!r}") from error
    return bytes.fromhex("02 0c 04 00 10 1d") + bytes((value, 0)) + bytes(56)


def set_brightness(level: int) -> None:
    send_hid_report(build_brightness_report(level), BRIGHTNESS_RESPONSE)


def set_sleep_timeout(minutes: str) -> None:
    send_hid_report(build_sleep_report(minutes), SLEEP_RESPONSE)


def set_sound_mode(mode: str) -> None:
    send_hid_report(build_sound_report(mode), SOUND_RESPONSE)


def read_bluetooth_status() -> dict[str, bool | str | None]:
    status_request = bytes.fromhex("02 0c 03 00 0e 0d 00") + bytes(57)
    status_response = exchange_hid_report(status_request, BLUETOOTH_STATUS_RESPONSE)
    connected = status_response[6]
    if connected not in (0, 1):
        raise ValueError(f"Unexpected Bluetooth connection state: {connected}")
    if not connected:
        return {"connected": False, "device_name": None}

    name_request = bytes.fromhex("02 0c 04 00 0e 2d 00") + bytes(57)
    name_response = exchange_hid_report(name_request, BLUETOOTH_NAME_RESPONSE)
    name_length = name_response[7]
    if name_length > len(name_response) - 8:
        raise ValueError("Invalid Bluetooth device-name length")
    name = name_response[8:8 + name_length].decode("utf-8").rstrip("\x00")
    return {"connected": True, "device_name": name or None}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage captured A50 base-station settings"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("bluetooth", help="Read Bluetooth connection and device name")
    brightness_parser = subparsers.add_parser(
        "brightness", help="Set base-station brightness from 0 to 100"
    )
    brightness_parser.add_argument("level", type=int)
    sleep_parser = subparsers.add_parser("sleep", help="Set the headset sleep timeout")
    sleep_parser.add_argument("minutes", choices=tuple(SLEEP_MINUTES))
    sound_parser = subparsers.add_parser("sound", help="Set the headset sound mode")
    sound_parser.add_argument("mode", choices=tuple(SOUND_MODE_IDS))
    subparsers.add_parser("list", help="List captured settings")
    args = parser.parse_args()

    try:
        if args.action == "bluetooth":
            print(json.dumps(read_bluetooth_status(), ensure_ascii=False))
            return 0
        if args.action == "brightness":
            set_brightness(args.level)
            print("Brightness command acknowledged; active value not read back")
        elif args.action == "sleep":
            set_sleep_timeout(args.minutes)
            print("Sleep-timeout command acknowledged; active value not read back")
        elif args.action == "sound":
            set_sound_mode(args.mode)
            print("Sound-mode command acknowledged; active value not read back")
        else:
            print(
                json.dumps(
                    {
                        "brightness": {"min": 0, "max": 100},
                        "sleep_minutes": list(SLEEP_MINUTES.values()),
                        "sound_modes": SOUND_MODE_IDS,
                    },
                    ensure_ascii=False,
                )
            )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 base-station command failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
