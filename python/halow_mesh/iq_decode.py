# SPDX-License-Identifier: GPL-3.0-or-later
"""GNU Radio message block: bounded IQ PDU to FCS-verified S1G MPDU PDUs."""

import numpy as np
import pmt
from gnuradio import gr

from .phy import decode_iq_window


class iq_decode(gr.basic_block):
    """Accept complex32 or interleaved signed-byte IQ in a PDU on ``in``.

    Each input is a bounded window. The sample rate, bandwidth, and offset
    are fixed when constructing the block, so later metadata cannot silently
    retune the receiver. ``sample_offset`` metadata is added to frame offsets.
    """

    def __init__(self, sample_rate, bandwidth_mhz, offset_hz=0, max_candidates=32):
        super().__init__(name="iq_decode", in_sig=None, out_sig=None)
        self.sample_rate = float(sample_rate)
        self.bandwidth_mhz = int(bandwidth_mhz)
        self.offset_hz = float(offset_hz)
        self.max_candidates = int(max_candidates)
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self.message_port_register_in(pmt.intern("in"))
        self.message_port_register_out(pmt.intern("out"))
        self.set_msg_handler(pmt.intern("in"), self._handle)

    def _handle(self, message):
        if not pmt.is_pair(message):
            raise ValueError("IQ input must be a metadata/payload PDU")
        metadata, payload = pmt.car(message), pmt.cdr(message)
        if pmt.is_c32vector(payload):
            samples = np.asarray(pmt.c32vector_elements(payload), dtype=np.complex64)
        elif pmt.is_u8vector(payload):
            raw = np.asarray(pmt.u8vector_elements(payload), dtype=np.uint8)
            if len(raw) % 2:
                raise ValueError("truncated interleaved signed-byte IQ")
            samples = raw.view(np.int8).reshape(-1, 2)
        else:
            raise ValueError("IQ PDU must contain c32vector or u8vector")
        offset = 0
        if pmt.is_dict(metadata):
            key = pmt.intern("sample_offset")
            value = pmt.dict_ref(metadata, key, pmt.PMT_NIL)
            if pmt.is_integer(value):
                offset = pmt.to_long(value)
        frames = decode_iq_window(samples, self.sample_rate, self.bandwidth_mhz,
                                  self.offset_hz, self.max_candidates)
        for frame in frames:
            output_meta = pmt.make_dict()
            fields = {
                "fcs_present": pmt.from_bool(True),
                "fcs_ok": pmt.from_bool(True),
                "sample_offset": pmt.from_long(offset+frame.sample_offset),
                "bandwidth_mhz": pmt.from_long(frame.bandwidth_mhz),
                "mcs": pmt.from_long(frame.mcs),
                "short_gi": pmt.from_bool(frame.short_gi),
                "cfo_hz": pmt.from_double(frame.cfo_hz),
                "ppdu_format": pmt.intern(frame.ppdu_format),
            }
            for name, value in fields.items():
                output_meta = pmt.dict_add(output_meta, pmt.intern(name), value)
            output = pmt.cons(output_meta, pmt.init_u8vector(len(frame.mpdu), list(frame.mpdu)))
            self.message_port_pub(pmt.intern("out"), output)
