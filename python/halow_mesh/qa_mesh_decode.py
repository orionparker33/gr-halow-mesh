#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocol and GNU Radio message-port integration checks."""

import json
import ctypes
import struct
import tempfile
import time
import unittest
import zlib

import pmt
from gnuradio import blocks, gr

from halow_mesh import decode_mpdu, iter_pcap, mesh_decode


def beacon():
    return (bytes.fromhex("1c680000") + bytes.fromhex("021122334455") +
            bytes(5) + bytes([114, 8]) + b"testmesh" +
            bytes([113, 7, 1, 1, 0, 1, 1, 3, 0x11]))


class TestMeshDecode(unittest.TestCase):
    def test_s1g_beacon_and_fcs(self):
        frame = beacon()
        event = decode_mpdu(frame)
        self.assertEqual(event["mesh_id"], "testmesh")
        self.assertEqual(event["mesh_config"]["peer_count"], 1)
        self.assertEqual(event["mesh_config"]["path_protocol"], 1)
        self.assertFalse(event["mesh_config"]["forwarding"])
        with_fcs = frame + zlib.crc32(frame).to_bytes(4, "little")
        self.assertEqual(decode_mpdu(with_fcs, fcs_present=True), event)
        with self.assertRaises(ValueError):
            decode_mpdu(with_fcs[:-1] + b"\0", fcs_present=True)

    def test_mesh_data_requires_context(self):
        frame = (bytes.fromhex("88000000") + bytes(18) + bytes(2) +
                 bytes.fromhex("0001") + bytes([0, 31]) +
                 (123).to_bytes(4, "little"))
        self.assertFalse(decode_mpdu(frame)["mesh"])
        self.assertEqual(decode_mpdu(frame, mesh_data=True)["mesh_control"]["sequence"], 123)
        with self.assertRaises(ValueError):
            decode_mpdu(frame[:-1], mesh_data=True)

    def test_message_port(self):
        tb = gr.top_block()
        # The 1 MHz C++ PHY emits a PMT blob. Build the same PMT type through
        # the Python binding rather than testing only Python u8vectors.
        buffer = ctypes.create_string_buffer(beacon())
        make_capsule = ctypes.pythonapi.PyCapsule_New
        make_capsule.restype = ctypes.py_object
        make_capsule.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        capsule = make_capsule(ctypes.cast(buffer, ctypes.c_void_p), None, None)
        packet = pmt.make_blob(capsule, len(beacon()))
        source = blocks.message_strobe(pmt.cons(pmt.make_dict(), packet), 10)
        parser = mesh_decode()
        sink = blocks.message_debug()
        tb.msg_connect(source, "strobe", parser, "in")
        tb.msg_connect(parser, "events", sink, "store")
        tb.start()
        try:
            deadline = time.monotonic() + 1
            while sink.num_messages() == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            tb.stop()
            tb.wait()
        self.assertGreater(sink.num_messages(), 0)
        message = sink.get_message(0)
        event = json.loads(bytes(pmt.u8vector_elements(pmt.cdr(message))))
        self.assertEqual(event["mesh_id"], "testmesh")

    def test_radiotap_pcap_adapter(self):
        frame = beacon()
        packet = (b"\x00\x00\x09\x00\x02\x00\x00\x00\x10" + frame +
                  zlib.crc32(frame).to_bytes(4, "little"))
        with tempfile.NamedTemporaryFile() as file:
            file.write(struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))
            file.write(struct.pack("<IIII", 0, 0, len(packet), len(packet)))
            file.write(packet)
            file.flush()
            records = list(iter_pcap(file.name))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1]["mesh_id"], "testmesh")


if __name__ == "__main__":
    unittest.main()
