#!/usr/bin/env python3
import argparse
import fcntl
import os
import select
import sys
import time
from pathlib import Path


DEVICE = "/dev/input/by-id/usb-Logitech_A50-if08-hidraw"
RESPONSE_PREFIX = bytes.fromhex("02 0c 03 00 09 1d")


def set_sidetone(level: int) -> None:
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 6:
        raise ValueError("Sidetone level must be an integer from 0 to 6")

    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    lock_path = Path(runtime) / "a50-hid.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(DEVICE, os.O_RDWR | os.O_NONBLOCK)
        try:
            request = bytes.fromhex("02 0c 06 00 09 1d 01 ff") + bytes([level]) + bytes(55)
            written = os.write(fd, request)
            if written != len(request):
                raise OSError(f"Incomplete HID request: {written}/{len(request)} bytes")
            deadline = time.monotonic() + 3
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise TimeoutError("Timed out waiting for the sidetone response")
                report = os.read(fd, 64)
                if not report:
                    raise OSError("A50 HID device disconnected")
                if report.startswith(RESPONSE_PREFIX):
                    if len(report) != 64 or report[6] != 0:
                        raise ValueError("Unexpected sidetone response")
                    return
        finally:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the experimental A50 sidetone level")
    parser.add_argument("level", type=int, choices=range(7), help="level from 0 to 6")
    args = parser.parse_args()
    try:
        set_sidetone(args.level)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 sidetone failed: {error}", file=sys.stderr)
        return 1
    print(f"Sidetone level {args.level}/6 accepted; current level is not read back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
