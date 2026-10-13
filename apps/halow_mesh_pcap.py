#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print recovered mesh MAC events from classic PCAP, one JSON object/line."""

import argparse
import json

from gnuradio.halow_mesh.pcap import iter_pcap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", help="radiotap (127) or raw IEEE 802.11 (105) PCAP")
    parser.add_argument("--all", action="store_true", help="include non-mesh MPDUs")
    parser.add_argument("--mesh-data", action="store_true",
                        help="interpret QoS mesh bit for captures known to be a mesh BSS")
    args = parser.parse_args()
    for number, event in iter_pcap(args.pcap, mesh_data=args.mesh_data):
        if event["mesh"] or args.all:
            print(json.dumps({"frame": number, **event}, sort_keys=True))


if __name__ == "__main__":
    main()
