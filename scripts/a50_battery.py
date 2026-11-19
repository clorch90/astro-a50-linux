#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import select
import sys
import time
from pathlib import Path


DEVICE = "/dev/input/by-id/usb-Logitech_A50-if08-hidraw"
REQUEST = bytes.fromhex("02 0c 03 00 06 0a") + bytes(58)
RESPONSE_PREFIX = bytes.fromhex("02 0c 06 00 06 0a")


def decode_battery(report: bytes) -> tuple[int, int, bool]:
    if len(report) != 64 or not report.startswith(RESPONSE_PREFIX):
        raise ValueError("Invalid A50 battery response")
    first, second, charging = report[6:9]
    if first > 100 or second > 100 or charging not in (0, 1):
        raise ValueError("Unknown A50 battery values or charging state")
    return first, second, bool(charging)


def read_battery() -> tuple[int, int, bool]:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    lock_path = Path(runtime) / "a50-hid.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(DEVICE, os.O_RDWR | os.O_NONBLOCK)
        try:
            written = os.write(fd, REQUEST)
            if written != len(REQUEST):
                raise OSError(f"Incomplete HID request: {written}/{len(REQUEST)} bytes")
            deadline = time.monotonic() + 3
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise TimeoutError("Timed out waiting for an A50 battery response")
                report = os.read(fd, 64)
                if not report:
                    raise OSError("A50 HID device disconnected")
                if report.startswith(RESPONSE_PREFIX):
                    return decode_battery(report)
        finally:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read the Astro A50 battery status")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()
    try:
        first, second, charging = read_battery()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 battery read failed: {error}", file=sys.stderr)
        return 1
    level = second if charging else first
    if args.json:
        print(json.dumps({
            "level": level,
            "charging": charging,
            "reported_values": [first, second],
            "experimental": True,
        }))
    else:
        print(f"Battery (experimental): {level}%")
        print(f"Charging: {'yes' if charging else 'no'}")
        print(f"Reported values: {first}, {second}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
