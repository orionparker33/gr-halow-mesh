# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite GNU Radio message source for recovered 802.11 frames in PCAP."""

import threading

import pmt
from gnuradio import gr

from .pcap import iter_pcap_frames


class pcap_source(gr.basic_block):
    """Publish radiotap/raw 802.11 PCAP records as MPDU PDUs, once per start."""

    def __init__(self, path):
        super().__init__(name="pcap_source", in_sig=None, out_sig=None)
        self.path = path
        self._stop_event = threading.Event()
        self._thread = None
        self.message_port_register_out(pmt.intern("out"))

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._publish, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return True

    def _publish(self):
        for number, frame, fcs_present, data_pad in iter_pcap_frames(self.path):
            if self._stop_event.is_set():
                break
            metadata = pmt.make_dict()
            metadata = pmt.dict_add(metadata, pmt.intern("pcap_record"), pmt.from_long(number))
            metadata = pmt.dict_add(metadata, pmt.intern("fcs_present"), pmt.from_bool(fcs_present))
            metadata = pmt.dict_add(metadata, pmt.intern("data_pad"), pmt.from_bool(data_pad))
            payload = pmt.init_u8vector(len(frame), list(frame))
            self.message_port_pub(pmt.intern("out"), pmt.cons(metadata, payload))
