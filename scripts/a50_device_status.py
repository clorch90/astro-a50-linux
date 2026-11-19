#!/usr/bin/env python3
import argparse
import json
import sys

from a50_equalizer import exchange_hid_report


REQUESTS = {
    "sidetone": ("02 0c 03 00 09 0e 00", "02 0c 07 00 09 0e"),
    "brightness": ("02 0c 03 00 0f 0e 00", "02 0c 04 00 0f 0e"),
    "sleep": ("02 0c 03 00 07 0e 00", "02 0c 05 00 07 0e"),
    "sound": ("02 0c 03 00 10 0e 00", "02 0c 04 00 10 0e"),
    "noise-gate": ("02 0c 03 00 14 1e 00", "02 0c 04 00 14 1e"),
    "output-eq": ("02 0c 05 00 0d 1e 01 03", "02 0c 36 00 0d 1e"),
    "microphone-eq": ("02 0c 05 00 0d 1e 00 03", "02 0c 36 00 0d 1e"),
}
EQ_FREQUENCIES = {
    "output-eq": (20, 50, 125, 250, 500, 1000, 2500, 5000, 10000, 20000),
    "microphone-eq": (80, 150, 250, 400, 800, 1500, 2500, 5000, 10000, 19000),
}


def decode_setting(name: str, response: bytes) -> int | list[float]:
    if name not in REQUESTS:
        raise ValueError(f"Unknown A50 setting: {name}")
    if len(response) != 64 or not response.startswith(bytes.fromhex(REQUESTS[name][1])):
        raise ValueError(f"Invalid {name} response")
    if name == "sidetone":
        if response[6:9] != bytes.fromhex("01 01 ff") or response[9] > 6:
            raise ValueError("Invalid sidetone response")
        return response[9]
    if name == "brightness":
        if response[6] > 100:
            raise ValueError("Invalid brightness response")
        return response[6]
    if name == "sleep":
        if response[6] != 60 or response[7] not in (0, 15, 30, 60):
            raise ValueError("Invalid sleep timeout response")
        return response[7]
    if name == "sound":
        if response[6] not in (0, 1, 2):
            raise ValueError("Invalid sound mode response")
        return response[6]
    if name == "noise-gate":
        if response[6] not in (0, 1, 2, 4):
            raise ValueError("Invalid noise-gate response")
        return response[6]

    gains = []
    for index, frequency in enumerate(EQ_FREQUENCIES[name]):
        offset = 7 + 5 * index
        if int.from_bytes(response[offset:offset + 2], "big") != frequency:
            raise ValueError(f"Unexpected {name} band frequency")
        raw = int.from_bytes(response[offset + 3:offset + 5], "big")
        if raw > 240 or raw % 10:
            raise ValueError(f"Unsupported {name} gain")
        gains.append((raw - 120) / 20)
    return gains


def read_setting(name: str) -> int | list[float]:
    if name not in REQUESTS:
        raise ValueError(f"Unknown A50 setting: {name}")
    request, prefix = REQUESTS[name]
    report = bytes.fromhex(request)
    response = exchange_hid_report(report + bytes(64 - len(report)), bytes.fromhex(prefix))
    return decode_setting(name, response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read captured A50 device settings")
    parser.add_argument("setting", choices=tuple(REQUESTS))
    args = parser.parse_args()
    try:
        print(json.dumps(read_setting(args.setting)))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 status read failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
