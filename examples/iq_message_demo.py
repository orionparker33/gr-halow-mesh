#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Feed one bounded signed-byte IQ window through both GNU Radio message blocks."""

import argparse
import json
import time

import numpy as np
import pmt
from gnuradio import gr, halow_mesh


class Source(gr.basic_block):
    def __init__(self):
        super().__init__(name="IQ PDU source", in_sig=None, out_sig=None)
        self.message_port_register_out(pmt.intern("out"))

    def send(self, raw, sample_offset):
        meta = pmt.dict_add(pmt.make_dict(), pmt.intern("sample_offset"),
                            pmt.from_long(sample_offset))
        packet = pmt.cons(meta, pmt.init_u8vector(len(raw), raw.tolist()))
        self.message_port_pub(pmt.intern("out"), packet)


class EventSink(gr.basic_block):
    def __init__(self):
        super().__init__(name="mesh event sink", in_sig=None, out_sig=None)
        self.count = 0
        self.message_port_register_in(pmt.intern("in"))
        self.set_msg_handler(pmt.intern("in"), self.handle)

    def handle(self, message):
        event = json.loads(bytes(pmt.u8vector_elements(pmt.cdr(message))))
        print(json.dumps(event, sort_keys=True), flush=True)
        self.count += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="interleaved signed-byte IQ file")
    parser.add_argument("--sample-rate", type=float, required=True)
    parser.add_argument("--bandwidth-mhz", type=int, choices=(1, 2, 4, 8), required=True)
    parser.add_argument("--offset-hz", type=float, default=0)
    parser.add_argument("--start", type=float, required=True, help="recording second")
    parser.add_argument("--duration-ms", type=float, default=10)
    args = parser.parse_args()
    if args.sample_rate <= 0 or args.start < 0 or not 1 <= args.duration_ms <= 50:
        parser.error("sample rate and start must be valid; window must be 1-50 ms")
    first = round(args.start * args.sample_rate)
    count = round(args.duration_ms * 1e-3 * args.sample_rate)
    with open(args.capture, "rb") as recording:
        recording.seek(first * 2)
        raw = np.frombuffer(recording.read(count * 2), dtype=np.uint8)
    if len(raw) != count * 2:
        parser.error("requested IQ window extends past the recording")

    graph = gr.top_block()
    source = Source()
    receiver = halow_mesh.iq_decode(args.sample_rate, args.bandwidth_mhz,
                                    args.offset_hz)
    mesh = halow_mesh.mesh_decode(emit_all=True)
    sink = EventSink()
    graph.msg_connect(source, "out", receiver, "in")
    graph.msg_connect(receiver, "out", mesh, "in")
    graph.msg_connect(mesh, "events", sink, "in")
    graph.start()
    try:
        source.send(raw, first)
        # Message blocks process synchronously on GNU Radio's work queue.
        # Wait briefly for the bounded example window, then stop the graph.
        time.sleep(1)
    finally:
        graph.stop()
        graph.wait()
    print(json.dumps({"mesh_events": sink.count}))


if __name__ == "__main__":
    main()
