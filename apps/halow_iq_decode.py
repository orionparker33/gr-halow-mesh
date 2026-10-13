#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode FCS-verified S1G MPDUs from a signed-byte IQ recording."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
import os
import struct

import numpy as np

from gnuradio.halow_mesh.phy import (decode_iq_window, detect_stf_raw,
                                    resample_phase_period, subband_power_fraction)


_worker_raw = None


def _init_worker(capture):
    global _worker_raw
    _worker_raw = np.memmap(capture, dtype=np.int8, mode="r").reshape(-1, 2)


def _decode_candidate(job):
    candidate, first, last, rate, width, offset, phase_period, ppdu_window = job
    pos = max(first, candidate-round(0.001*rate))
    aligned = pos-pos%phase_period
    pos = aligned if aligned >= first else aligned+phase_period
    end = min(last, candidate+round(ppdu_window*rate))
    if end-pos < round(0.001*rate):
        return ()
    # The sparse raw detector sits within a few samples of the STF on the
    # measured 8 MHz path. A two-millisecond fine search retains the 1 ms
    # lead-in while avoiding unnecessary full-band work on false peaks.
    search_seconds = .002 if width == 8 else .003
    return tuple((pos+frame.sample_offset, frame) for frame in decode_iq_window(
        _worker_raw[pos:end], rate, width, offset, max_candidates=4,
        search_duration=min(search_seconds, (end-pos)/rate),
        candidate_hint=candidate-pos))


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
    parser.add_argument("--stf-threshold", type=float, default=.75,
                        help="raw preamble detector threshold (0-1; higher is faster but less sensitive)")
    parser.add_argument("--start", type=float, default=0, help="first recording second")
    parser.add_argument("--duration", type=float, help="seconds to process")
    parser.add_argument("--workers", type=int, default=0,
                        help="decoder processes (0: auto, 1: serial)")
    parser.add_argument("--max-subband-fraction", type=float, default=1.0,
                        help="optional 8 MHz coarse filter: reject candidates with more than this fraction of power in any 2 MHz band (default 1, disabled)")
    parser.add_argument("--max-ppdu-ms", type=float, default=0,
                        help="IQ retained after each coarse candidate (0: 200 ms at 2/4/8 MHz, 30 ms at 1 MHz; explicit range 1-200 ms)")
    parser.add_argument("--pcap", help="write radiotap PCAP with verified FCS")
    parser.add_argument("--start-utc", help="ISO 8601 UTC time of first IQ sample")
    args = parser.parse_args()
    if not np.isfinite(args.sample_rate) or args.sample_rate < 2e6:
        parser.error("--sample-rate must be finite and at least 2 Msps for raw detection")
    if not np.isfinite(args.offset_hz) or abs(args.offset_hz)+args.bandwidth_mhz*0.5e6 > args.sample_rate*0.5:
        parser.error("selected channel must fit inside the sampled Nyquist span")
    if (not np.isfinite(args.start) or args.start < 0 or
            (args.duration is not None and (not np.isfinite(args.duration) or args.duration <= 0))):
        parser.error("start must be nonnegative and duration positive")
    if not 0 < args.stf_threshold <= 1:
        parser.error("--stf-threshold must be greater than 0 and at most 1")
    if args.workers < 0:
        parser.error("--workers must be nonnegative")
    if (not np.isfinite(args.max_subband_fraction) or
            not 0 < args.max_subband_fraction <= 1):
        parser.error("--max-subband-fraction must be greater than 0 and at most 1")
    if args.max_subband_fraction < 1 and args.bandwidth_mhz != 8:
        parser.error("--max-subband-fraction currently applies only to 8 MHz")
    if (not np.isfinite(args.max_ppdu_ms) or args.max_ppdu_ms < 0 or
            args.max_ppdu_ms > 200 or 0 < args.max_ppdu_ms < 1):
        parser.error("--max-ppdu-ms must be 0 (auto) or between 1 and 200")
    if args.pcap and not args.start_utc:
        parser.error("--pcap requires --start-utc for packet timestamps")
    epoch = 0.0
    if args.start_utc:
        value = args.start_utc.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            parser.error("--start-utc must include UTC timezone")
        epoch = timestamp.astimezone(timezone.utc).timestamp()
    raw = np.memmap(args.capture, dtype=np.int8, mode="r")
    if len(raw) % 2:
        parser.error("IQ file has a truncated I/Q pair")
    raw = raw.reshape(-1, 2)
    first = round(args.start * args.sample_rate)
    last = min(len(raw), first+round(args.duration*args.sample_rate)) if args.duration else len(raw)
    if first >= last:
        parser.error("requested interval is outside capture")
    scan_step = round(0.5*args.sample_rate)
    scan_overlap = round(0.001*args.sample_rate)
    phase_period = resample_phase_period(args.sample_rate,args.bandwidth_mhz)
    ppdu_window = (args.max_ppdu_ms if args.max_ppdu_ms else
                   (30 if args.bandwidth_mhz == 1 else 200))/1000
    output = None
    if args.pcap:
        try:
            fd = os.open(args.pcap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            output = os.fdopen(fd, "wb")
        except OSError as exc:
            parser.error(f"cannot create new private PCAP: {exc}")
    if output:
        output.write(_pcap_header())
    seen = []
    count = 0
    completed = False
    try:
        candidates=[]
        for pos in range(first,last,scan_step):
            end=min(pos+scan_step+scan_overlap,last)
            candidates.extend(pos+peak for peak in detect_stf_raw(
                raw[pos:end],args.sample_rate,args.stf_threshold))
        deduplicated=[]
        for candidate in sorted(candidates):
            if not deduplicated or candidate-deduplicated[-1]>round(args.sample_rate*0.00015):
                deduplicated.append(candidate)
        if args.max_subband_fraction < 1:
            def within_bandwidth(candidate):
                fraction = subband_power_fraction(raw, candidate,
                                                  args.sample_rate)
                return fraction is None or fraction <= args.max_subband_fraction

            deduplicated = [candidate for candidate in deduplicated
                            if within_bandwidth(candidate)]
        workers = args.workers or (min(4, os.cpu_count() or 1)
                                   if len(deduplicated) >= 128 else 1)
        jobs = ((candidate, first, last, args.sample_rate, args.bandwidth_mhz,
                 args.offset_hz, phase_period, ppdu_window) for candidate in deduplicated)
        if workers == 1:
            _init_worker(args.capture)
            results = map(_decode_candidate, jobs)
            pool = None
        else:
            pool = ProcessPoolExecutor(max_workers=workers,
                                       initializer=_init_worker,
                                       initargs=(args.capture,))
            results = pool.map(_decode_candidate, jobs, chunksize=32)
        try:
            for decoded in results:
                for absolute, frame in decoded:
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
            if pool:
                pool.shutdown(cancel_futures=True)
        completed = True
    finally:
        if output:
            output.close()
            if not completed:
                os.unlink(args.pcap)
    print(json.dumps({"verified_frames": count, "pcap": args.pcap}), flush=True)


if __name__ == "__main__":
    main()
