#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode FCS-verified S1G MPDUs from a signed-byte IQ recording."""

import argparse
from datetime import datetime, timezone
import json
import struct

import numpy as np

from gnuradio.halow_mesh.phy import decode_iq_window, detect_stf_raw


def _pcap_header():
    # Classic PCAP, radiotap link type, little endian, microsecond timestamps.
    return struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 262144, 127)


def _radiotap_fcs():
    # Flags present; bit 4 says each MPDU contains its four-byte FCS.
    return struct.pack("<BBHI", 0, 0, 9, 1 << 1) + b"\x10"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="interleaved signed 8-bit I/Q file")
    parser.add_argument("--sample-rate", type=float, required=True)
    parser.add_argument("--bandwidth-mhz", type=int, choices=(1, 2, 4, 8), required=True)
    parser.add_argument("--offset-hz", type=float, default=0)
    parser.add_argument("--start", type=float, default=0, help="first recording second")
    parser.add_argument("--duration", type=float, help="seconds to process")
    parser.add_argument("--pcap", help="write radiotap PCAP with verified FCS")
    parser.add_argument("--start-utc", help="ISO 8601 UTC time of first IQ sample")
    args = parser.parse_args()
    if args.start < 0 or (args.duration is not None and args.duration <= 0):
        parser.error("start must be nonnegative and duration positive")
    if args.pcap and not args.start_utc:
        parser.error("--pcap requires --start-utc for packet timestamps")
    epoch = 0.0
    if args.start_utc:
        value = args.start_utc.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            parser.error("--start-utc must include UTC timezone")
        epoch = timestamp.astimezone(timezone.utc).timestamp()
    raw = np.memmap(args.capture, dtype=np.int8)
    if len(raw) % 2:
        parser.error("IQ file has a truncated I/Q pair")
    raw = raw.reshape(-1, 2)
    first = round(args.start * args.sample_rate)
    last = min(len(raw), first+round(args.duration*args.sample_rate)) if args.duration else len(raw)
    if first >= last:
        parser.error("requested interval is outside capture")
    scan_step = round(0.5*args.sample_rate)
    scan_overlap = round(0.001*args.sample_rate)
    output = open(args.pcap, "wb") if args.pcap else None
    if output:
        output.write(_pcap_header())
    seen = []
    count = 0
    try:
        candidates=[]
        for pos in range(first,last,scan_step):
            end=min(pos+scan_step+scan_overlap,last)
            candidates.extend(pos+peak for peak in detect_stf_raw(raw[pos:end],args.sample_rate))
        deduplicated=[]
        for candidate in sorted(candidates):
            if not deduplicated or candidate-deduplicated[-1]>round(args.sample_rate*0.00015):
                deduplicated.append(candidate)
        for candidate in deduplicated:
            pos=max(first,candidate-round(0.001*args.sample_rate))
            end=min(last,candidate+round(0.030*args.sample_rate))
            if end-pos<round(0.001*args.sample_rate):
                continue
            for frame in decode_iq_window(raw[pos:end],args.sample_rate,
                                          args.bandwidth_mhz,args.offset_hz,max_candidates=4,
                                          search_duration=min(.003,(end-pos)/args.sample_rate)):
                absolute=pos+frame.sample_offset
                if any(prior.mpdu == frame.mpdu and abs(at-absolute) < round(args.sample_rate*0.0002)
                       for at, prior in seen):
                    continue
                seen.append((absolute, frame))
                seen = [(at, prior) for at, prior in seen if at > absolute-round(args.sample_rate*0.1)]
                event = {
                    "sample_offset": absolute,
                    "recording_second": round(absolute/args.sample_rate, 9),
                    "bandwidth_mhz": frame.bandwidth_mhz,
                    "mcs": frame.mcs,
                    "ppdu_format": frame.ppdu_format,
                    "short_gi": frame.short_gi,
                    "cfo_hz": round(frame.cfo_hz, 1),
                    "mpdu_bytes": len(frame.mpdu),
                    "fcs_ok": True,
                }
                print(json.dumps(event, sort_keys=True), flush=True)
                if output:
                    ts = epoch+absolute/args.sample_rate
                    seconds = int(ts)
                    micros = round((ts-seconds)*1e6)
                    if micros >= 1_000_000:
                        seconds, micros = seconds+1, micros-1_000_000
                    packet = _radiotap_fcs()+frame.mpdu
                    output.write(struct.pack("<IIII", seconds, micros, len(packet), len(packet)))
                    output.write(packet)
                count += 1
    finally:
        if output:
            output.close()
    print(json.dumps({"verified_frames": count, "pcap": args.pcap}), flush=True)


if __name__ == "__main__":
    main()
