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

import numpy as np
import pmt
from gnuradio import blocks, gr

from halow_mesh import decode_mpdu, iter_pcap, mesh_decode, pcap_source
from halow_mesh.iq_probe import inspect_iq


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

    def test_pcap_source_graph_with_fcs(self):
        frame = beacon()
        packet = (b"\x00\x00\x09\x00\x02\x00\x00\x00\x10" + frame +
                  zlib.crc32(frame).to_bytes(4, "little"))
        with tempfile.NamedTemporaryFile() as file:
            file.write(struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))
            file.write(struct.pack("<IIII", 0, 0, len(packet), len(packet)))
            file.write(packet)
            file.flush()
            tb = gr.top_block()
            source = pcap_source(file.name)
            parser = mesh_decode()
            sink = blocks.message_debug()
            tb.msg_connect(source, "out", parser, "in")
            tb.msg_connect(parser, "events", sink, "store")
            tb.start()
            try:
                deadline = time.monotonic() + 1
                while sink.num_messages() == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
            finally:
                tb.stop()
                tb.wait()
            self.assertEqual(sink.num_messages(), 1)
            event = json.loads(bytes(pmt.u8vector_elements(pmt.cdr(sink.get_message(0)))))
            self.assertEqual(event["mesh_id"], "testmesh")

    def test_iq_probe_distinguishes_ofdm_tone_and_noise(self):
        rng = np.random.default_rng(20261013)
        symbols = []
        for _ in range(8):
            tones = np.zeros(320, complex)
            tones[1:111] = rng.choice([-1, 1], 110)
            tones[-110:] = rng.choice([-1, 1], 110)
            symbol = np.fft.ifft(tones) * 600
            symbols.append(np.r_[symbol[-80:], symbol])
        ofdm = np.r_[np.zeros(500), *symbols, np.zeros(500)]
        tone = np.exp(2j * np.pi * .02 * np.arange(len(ofdm))) * 30
        noise = rng.normal(size=len(ofdm)) + 1j * rng.normal(size=len(ofdm))

        def measure(signal):
            samples = np.stack((signal.real, signal.imag), axis=1).astype(np.int8)
            return inspect_iq(samples, 10e6, 8)

        ofdm_result, tone_result, noise_result = map(measure, (ofdm, tone, noise))
        self.assertGreater(ofdm_result["cp_score"], .9)
        self.assertGreater(ofdm_result["effective_fft_bins"], 100)
        self.assertGreater(tone_result["cp_score"], .9)
        self.assertLess(tone_result["effective_fft_bins"], 8)
        self.assertLess(noise_result["cp_score"], .5)

        narrow_result = inspect_iq(
            np.stack((ofdm.real, ofdm.imag), axis=1).astype(np.int8), 10e6, 2)
        self.assertLess(narrow_result["selected_band_energy_fraction"], .4)
        self.assertGreater(ofdm_result["selected_band_energy_fraction"], .8)

        with self.assertRaises(ValueError):
            inspect_iq(np.zeros((2000, 2), dtype=np.int8), 10e6, 16)
        wide = inspect_iq(np.zeros((2000, 2), dtype=np.int8), 20e6, 16)
        self.assertEqual(wide["bandwidth_mhz"], 16)


if __name__ == "__main__":
    unittest.main()
