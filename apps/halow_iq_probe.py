#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect a short signed-8-bit IQ window for OFDM cyclic-prefix structure."""

import argparse
import json

import numpy as np

from gnuradio.halow_mesh.iq_probe import inspect_iq


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="interleaved signed-8-bit I/Q file")
    parser.add_argument("--sample-rate", type=float, required=True, help="complex samples/second")
    parser.add_argument("--bandwidth-mhz", type=int, required=True, choices=(1, 2, 4, 8, 16),
                        help="channel width to analyze; 16 MHz needs an independent reference")
    parser.add_argument("--offset-hz", type=float, default=0,
                        help="selected channel center relative to recording center")
    parser.add_argument("--start", type=float, required=True, help="window start in seconds")
    parser.add_argument("--duration-ms", type=float, default=4.0,
                        help="window duration in milliseconds, maximum 100")
    args = parser.parse_args()
    if args.start < 0 or not 0.1 <= args.duration_ms <= 100:
        parser.error("start must be nonnegative and duration 0.1..100 ms")
    raw = np.memmap(args.capture, dtype=np.int8)
    if len(raw) % 2:
        parser.error("truncated interleaved I/Q file")
    first = round(args.start * args.sample_rate)
    count = round(args.duration_ms * 1e-3 * args.sample_rate)
    samples = raw.reshape(-1, 2)[first:first + count]
    if len(samples) != count:
        parser.error("requested window exceeds capture")
    try:
        result = inspect_iq(samples, args.sample_rate, args.bandwidth_mhz, args.offset_hz)
    except ValueError as exc:
        parser.error(str(exc))
    result["peak_seconds"] = round((first + result["sample_offset"]) / args.sample_rate, 7)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
