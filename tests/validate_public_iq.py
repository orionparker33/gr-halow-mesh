#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare decoded third-party 2 MHz IQ against its published PCAP.

The input is the first seconds of Daniel Estévez's ci16_le, 3.84 Msps
802.11ah SigMF data, extracted from his published tar archive. The PCAP
comes from the same author's published notebook repository. Neither capture
is bundled with this project.
"""

import argparse
import struct

import numpy as np

from halow_mesh.phy import decode_iq_window


def reference_frames(path):
    frames = set()
    with open(path, "rb") as source:
        header = source.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1" or struct.unpack_from("<I", header, 20)[0] != 127:
            raise ValueError("reference must be little-endian radiotap PCAP")
        while record := source.read(16):
            if len(record) != 16:
                raise ValueError("truncated PCAP record header")
            _, _, size, _ = struct.unpack("<IIII", record)
            if size > 262144:
                raise ValueError("oversized PCAP record")
            packet = source.read(size)
            if len(packet) != size or size < 4:
                raise ValueError("truncated PCAP record")
            radiotap_length = struct.unpack_from("<H", packet, 2)[0]
            if radiotap_length > len(packet):
                raise ValueError("invalid radiotap length")
            frames.add(packet[radiotap_length:])
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iq", help="extracted ci16_le SigMF data, or its first 32 MB")
    parser.add_argument("pcap", help="published 802_11_ah.pcap reference")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--min-frames", type=int, default=20)
    args = parser.parse_args()
    rate = 3_840_000
    iq = np.memmap(args.iq, dtype="<i2")
    if len(iq) % 2:
        parser.error("truncated I/Q pair")
    iq = iq.reshape(-1, 2)
    last = min(len(iq), round(args.seconds * rate))
    if last < round(.06 * rate):
        parser.error("at least 60 ms of IQ is required")
    refs = reference_frames(args.pcap)
    seen = set()
    matched = 0
    decoded = 0
    for pos in range(0, last - round(.01 * rate), round(.05 * rate)):
        end = min(last, pos + round(.06 * rate))
        if end - pos < round(.01 * rate):
            continue
        pair = iq[pos:end].astype(np.float32)
        samples = pair[:, 0] + 1j * pair[:, 1]
        for frame in decode_iq_window(samples, rate, 2, max_candidates=16):
            key = (pos + frame.sample_offset, frame.mpdu)
            if key in seen:
                continue
            seen.add(key)
            decoded += 1
            matched += frame.mpdu in refs
    print(f"decoded={decoded} exact_pcap_matches={matched} reference_records={len(refs)}")
    if decoded < args.min_frames or matched != decoded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
