#!/usr/bin/env python3
import argparse
import json
import sys

from a50_equalizer import send_hid_report


NOISE_GATE_STATES = {
    "Aus": 0,
    "Nacht": 2,
    "Zu Hause": 1,
    "Turnier": 4,
}
RESPONSE_PREFIX = bytes.fromhex("02 0c 04 00 14 00")


def build_report(state: str) -> bytes:
    try:
        state_id = NOISE_GATE_STATES[state]
    except KeyError as error:
        raise ValueError(f"Unknown microphone noise-gate state: {state!r}") from error
    return bytes.fromhex("02 0c 04 00 14 2e") + bytes((state_id, 0)) + bytes(56)


def apply_state(state: str) -> None:
    state_id = NOISE_GATE_STATES.get(state)
    if state_id is None:
        raise ValueError(f"Unknown microphone noise-gate state: {state!r}")
    send_hid_report(
        build_report(state),
        RESPONSE_PREFIX + bytes((state_id,)),
        response_status=state_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set the experimental A50 microphone noise gate"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", help="List captured noise-gate states")
    set_parser = subparsers.add_parser("set", help="Set a microphone noise-gate state")
    set_parser.add_argument("state", choices=tuple(NOISE_GATE_STATES))
    args = parser.parse_args()

    try:
        if args.action == "list":
            print(json.dumps(NOISE_GATE_STATES, ensure_ascii=False))
        else:
            apply_state(args.state)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A50 microphone noise gate failed: {error}", file=sys.stderr)
        return 1
    if args.action == "set":
        print(
            f"Microphone noise-gate command for {args.state!r} acknowledged; "
            "the current state was not read back"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
