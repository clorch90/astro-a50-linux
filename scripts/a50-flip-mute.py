#!/usr/bin/python3
import json
import logging
import os
import select
import subprocess
import time
from pathlib import Path


DEVICE = "/dev/input/by-id/usb-Logitech_A50-if08-hidraw"
SOURCE_NAMES = {
    "alsa_input.usb-Logitech_A50-00.pro-input-0",
    "alsa_input.usb-Logitech_A50-00.pro-input-1",
}
SOUND_DIR = Path.home() / ".local/share/toggle-mic-mute-sounds"
EVENT_PREFIX = bytes.fromhex("02 0c 07 00 0c 00 00 00 00")


def event_mute(report: bytes) -> bool | None:
    if len(report) != 64 or not report.startswith(EVENT_PREFIX):
        return None
    return {0x0A: True, 0x0B: False}.get(report[9])


def set_mute(muted: bool) -> None:
    result = subprocess.run(
        ["pw-dump"], check=True, capture_output=True, text=True, timeout=5
    )
    nodes = json.loads(result.stdout)
    sources = {}
    for node in nodes:
        props = node.get("info", {}).get("props", {})
        name = props.get("node.name")
        if name in SOURCE_NAMES and props.get("media.class") == "Audio/Source":
            sources[name] = node["id"]
    if sources.keys() != SOURCE_NAMES:
        raise RuntimeError("A50 microphone sources are not both available")
    for name in sorted(SOURCE_NAMES):
        subprocess.run(
            ["wpctl", "set-mute", str(sources[name]), "1" if muted else "0"],
            check=True,
            timeout=5,
        )


def play_sound(muted: bool) -> None:
    sound = SOUND_DIR / ("mute.wav" if muted else "unmute.wav")
    subprocess.run(
        ["paplay", "--volume=65536", str(sound)], check=True, timeout=5
    )


def monitor(fd: int) -> None:
    pending = None
    retry_at = 0.0
    while True:
        wait = max(0.0, retry_at - time.monotonic()) if pending is not None else None
        ready, _, _ = select.select([fd], [], [], wait)
        if ready:
            report = os.read(fd, 64)
            if not report:
                raise OSError("A50 HID device disconnected")
            state = event_mute(report)
            if state is not None:
                pending = state
                retry_at = 0.0
        if pending is not None and time.monotonic() >= retry_at:
            try:
                set_mute(pending)
            except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                logging.warning("Could not set A50 microphone mute: %s", error)
                retry_at = time.monotonic() + 2
                continue
            logging.info("A50 microphone %s", "muted" if pending else "unmuted")
            try:
                play_sound(pending)
            except (OSError, subprocess.SubprocessError) as error:
                logging.warning("Could not play microphone sound: %s", error)
            pending = None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    while True:
        try:
            fd = os.open(DEVICE, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            time.sleep(2)
            continue
        except OSError as error:
            logging.error("Could not open A50 HID device: %s", error)
            time.sleep(2)
            continue
        try:
            logging.info("Listening for A50 microphone arm events")
            monitor(fd)
        except OSError as error:
            logging.warning("A50 HID device disconnected: %s", error)
        finally:
            os.close(fd)
        time.sleep(2)


if __name__ == "__main__":
    main()
