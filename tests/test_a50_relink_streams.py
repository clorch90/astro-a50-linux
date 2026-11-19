import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a50_relink_streams.py"
spec = importlib.util.spec_from_file_location("a50_relink_streams", SCRIPT)
assert spec and spec.loader
relink = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relink)

SINK = "alsa_output.usb-Logitech_A50-00.pro-output-1"


def node(node_id, props):
    return {"id": node_id, "type": "PipeWire:Interface:Node", "info": {"props": props}}


def port(port_id, node_id, direction):
    props = {"node.id": node_id, "port.direction": direction}
    return {"id": port_id, "type": "PipeWire:Interface:Port", "info": {"props": props}}


def link(output_node):
    return {"id": 900, "type": "PipeWire:Interface:Link", "info": {"output-node-id": output_node}}


def objects(with_link=False, target=SINK):
    result = [
        node(77, {"node.name": SINK, "media.class": "Audio/Sink"}),
        node(86, {"media.class": "Stream/Output/Audio", "target.object": target}),
        port(1, 86, "out"), port(2, 86, "out"),
        port(10, 77, "in"), port(11, 77, "in"),
    ]
    if with_link:
        result.append(link(86))
    return result


class FindOrphansTest(unittest.TestCase):
    def test_unlinked_stream_targeting_a50_is_paired_port_by_port(self):
        self.assertEqual(relink.find_orphans(objects()), [(86, [(1, 10), (2, 11)])])

    def test_linked_stream_is_ignored(self):
        self.assertEqual(relink.find_orphans(objects(with_link=True)), [])

    def test_stream_for_other_target_is_ignored(self):
        self.assertEqual(relink.find_orphans(objects(target="other")), [])


if __name__ == "__main__":
    unittest.main()
