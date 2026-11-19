#!/usr/bin/python3
"""Reconnect orphaned playback streams to the A50 after it re-enumerates.

Some applications (e.g. Wine/Proton games) ask PipeWire not to reconnect
their stream. After a PlaySync switch the A50 disappears briefly, and such
streams stay unlinked. This service links them to the sink they target.
"""
import json
import subprocess
import time

SINKS = {
    "alsa_output.usb-Logitech_A50-00.pro-output-0",
    "alsa_output.usb-Logitech_A50-00.pro-output-1",
}
POLL_SECONDS = 2
# Streams must stay unlinked for this many polls before we step in, so
# WirePlumber gets a chance to link normal streams itself.
ORPHAN_POLLS = 2


def pw_dump():
    result = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(result.stdout)


def find_orphans(objects):
    """Return (stream_id, [(out_port_id, in_port_id), ...]) for unlinked streams."""
    sink_ids = {}
    linked_nodes = set()
    ports = {}
    streams = {}
    for obj in objects:
        info = obj.get("info", {})
        props = info.get("props", {})
        kind = obj.get("type", "")
        if kind.endswith("Node"):
            if props.get("node.name") in SINKS:
                sink_ids[props["node.name"]] = obj["id"]
            elif props.get("media.class") == "Stream/Output/Audio":
                streams[obj["id"]] = props
        elif kind.endswith("Link"):
            linked_nodes.add(info.get("output-node-id"))
        elif kind.endswith("Port"):
            ports.setdefault(props.get("node.id"), []).append((obj["id"], props))

    orphans = []
    for stream_id, props in streams.items():
        target = props.get("target.object")
        if target not in sink_ids or stream_id in linked_nodes:
            continue
        outputs = sorted(
            (pid, p) for pid, p in ports.get(stream_id, []) if p.get("port.direction") == "out"
        )
        inputs = sorted(
            (pid, p)
            for pid, p in ports.get(sink_ids[target], [])
            if p.get("port.direction") == "in"
        )
        pairs = [
            (out_id, in_id)
            for (out_id, _), (in_id, _) in zip(outputs, inputs)
        ]
        if pairs:
            orphans.append((stream_id, pairs))
    return orphans


def relink(pairs):
    for out_id, in_id in pairs:
        subprocess.run(["pw-link", str(out_id), str(in_id)], capture_output=True, timeout=5)


def main():
    seen = {}
    while True:
        try:
            orphans = dict(find_orphans(pw_dump()))
        except (subprocess.SubprocessError, ValueError, OSError):
            orphans = {}
        seen = {sid: seen.get(sid, 0) + 1 for sid in orphans}
        for stream_id, count in seen.items():
            if count >= ORPHAN_POLLS:
                relink(orphans[stream_id])
                seen[stream_id] = 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
