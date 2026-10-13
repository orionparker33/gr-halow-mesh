# SPDX-License-Identifier: GPL-3.0-or-later
"""GNU Radio message block: bounded IQ PDU to FCS-verified S1G MPDU PDUs."""

import numpy as np
import pmt
from gnuradio import gr

from .phy import decode_iq_window, detect_stf_raw


def _publish_frame(block, frame, sample_offset):
    output_meta = pmt.make_dict()
    fields = {
        "fcs_present": pmt.from_bool(True),
        "fcs_ok": pmt.from_bool(True),
        "sample_offset": pmt.from_long(sample_offset+frame.sample_offset),
        "bandwidth_mhz": pmt.from_long(frame.bandwidth_mhz),
        "mcs": pmt.from_long(frame.mcs),
        "short_gi": pmt.from_bool(frame.short_gi),
        "cfo_hz": pmt.from_double(frame.cfo_hz),
        "ppdu_format": pmt.intern(frame.ppdu_format),
    }
    for name, value in fields.items():
        output_meta = pmt.dict_add(output_meta, pmt.intern(name), value)
    output = pmt.cons(output_meta, pmt.init_u8vector(len(frame.mpdu), list(frame.mpdu)))
    block.message_port_pub(pmt.intern("out"), output)


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
            _publish_frame(self, frame, offset)


class iq_stream_decode(gr.sync_block):
    """Consume a complex stream in overlapping windows and publish MPDU PDUs.

    Processing occurs in the GNU Radio work thread. Hardware sources can lose
    samples if this receiver falls behind; this block does not claim real-time
    or lossless capture. The stream must be continuous from sample offset zero.
    """

    def __init__(self, sample_rate, bandwidth_mhz, offset_hz=0,
                 window_seconds=.1, overlap_seconds=.03, max_candidates=8,
                 stf_threshold=.75):
        super().__init__(name="iq_stream_decode", in_sig=[np.complex64], out_sig=None)
        self.sample_rate = float(sample_rate)
        self.bandwidth_mhz = int(bandwidth_mhz)
        self.offset_hz = float(offset_hz)
        self.max_candidates = int(max_candidates)
        self.stf_threshold = float(stf_threshold)
        if (not np.isfinite(self.sample_rate) or self.sample_rate <= 0 or
                not np.isfinite(self.offset_hz) or self.bandwidth_mhz not in (1,2,4,8) or
                abs(self.offset_hz)+self.bandwidth_mhz*5e5 > self.sample_rate/2 or
                not np.isfinite(window_seconds) or not np.isfinite(overlap_seconds) or
                window_seconds < .05 or overlap_seconds < .03 or
                window_seconds-overlap_seconds < .01 or self.max_candidates < 1 or
                not np.isfinite(self.stf_threshold) or not 0 < self.stf_threshold <= 1):
            raise ValueError("invalid IQ stream width, rate, offset, window, overlap, or candidate limit")
        self.window_samples = round(window_seconds*self.sample_rate)
        self.overlap_samples = round(overlap_seconds*self.sample_rate)
        if self.window_samples > 10_000_000 or self.window_samples <= self.overlap_samples:
            raise ValueError("IQ stream window exceeds the bounded buffer")
        self._buffer = np.empty(self.window_samples, dtype=np.complex64)
        self._filled = 0
        self._window_start = 0
        self._seen = []
        self.message_port_register_out(pmt.intern("out"))

    def start(self):
        self._filled = 0
        self._window_start = 0
        self._seen = []
        return True

    def _process(self, size):
        values = self._buffer[:size]
        if self.sample_rate < 2e6:
            frames = decode_iq_window(values, self.sample_rate,
                                      self.bandwidth_mhz, self.offset_hz,
                                      self.max_candidates)
            for frame in frames:
                absolute = self._window_start + frame.sample_offset
                if any(body == frame.mpdu and abs(absolute-prior) < round(self.sample_rate*.00005)
                       for prior, body in self._seen):
                    continue
                _publish_frame(self, frame, self._window_start)
                self._seen.append((absolute, frame.mpdu))
            cutoff = self._window_start + size - self.overlap_samples - round(self.sample_rate*.001)
            self._seen = [(at, body) for at, body in self._seen if at >= cutoff]
            return
        candidates = sorted(detect_stf_raw(values, self.sample_rate,
                                           self.stf_threshold))
        deduplicated = []
        for candidate in candidates:
            if not deduplicated or candidate-deduplicated[-1] > round(self.sample_rate*.00015):
                deduplicated.append(candidate)
        for candidate in deduplicated[:self.max_candidates]:
            first = max(0, candidate-round(self.sample_rate*.001))
            last = min(size, candidate+round(self.sample_rate*.06))
            if last-first < round(self.sample_rate*.001):
                continue
            frames = decode_iq_window(values[first:last], self.sample_rate,
                                      self.bandwidth_mhz, self.offset_hz,
                                      self.max_candidates,
                                      search_duration=min(.003,(last-first)/self.sample_rate))
            for frame in frames:
                absolute = self._window_start + first + frame.sample_offset
                if any(body == frame.mpdu and abs(absolute-prior) < round(self.sample_rate*.00005)
                       for prior, body in self._seen):
                    continue
                _publish_frame(self, frame, self._window_start+first)
                self._seen.append((absolute, frame.mpdu))
        # Retain only offsets that can appear in the next overlapping window.
        cutoff = self._window_start + size - self.overlap_samples - round(self.sample_rate*.001)
        self._seen = [(at, body) for at, body in self._seen if at >= cutoff]

    def work(self, input_items, output_items):
        values = input_items[0]
        position = 0
        while position < len(values):
            take = min(len(values)-position, self.window_samples-self._filled)
            self._buffer[self._filled:self._filled+take] = values[position:position+take]
            self._filled += take
            position += take
            if self._filled == self.window_samples:
                self._process(self.window_samples)
                self._buffer[:self.overlap_samples] = self._buffer[-self.overlap_samples:].copy()
                self._window_start += self.window_samples-self.overlap_samples
                self._filled = self.overlap_samples
        return len(values)

    def stop(self):
        if self._filled >= round(self.sample_rate*.001):
            self._process(self._filled)
        self._filled = 0
        return True
