# SPDX-License-Identifier: GPL-3.0-or-later
"""Classic PCAP adapter for recovered 802.11 MPDUs."""

import struct

from .protocol import decode_mpdu


def iter_pcap(path, *, mesh_data=False):
    """Yield (record number, decoded event) for radiotap or raw 802.11 PCAP."""
    with open(path, "rb") as source:
        header = source.read(24)
        if len(header) != 24:
            raise ValueError("short PCAP header")
        magic = header[:4]
        if magic not in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4",
                         b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
            raise ValueError("unsupported PCAP magic")
        endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
        linktype = struct.unpack_from(endian + "I", header, 20)[0]
        if linktype not in (105, 127):
            raise ValueError("PCAP link type must be IEEE 802.11 or radiotap")
        number = 0
        while packet_header := source.read(16):
            if len(packet_header) != 16:
                raise ValueError("short PCAP record header")
            _sec, _subsec, caplen, _wirelen = struct.unpack(endian + "IIII", packet_header)
            if caplen > 4 * 1024 * 1024:
                raise ValueError("oversize PCAP record")
            data = source.read(caplen)
            if len(data) != caplen:
                raise ValueError("short PCAP record")
            number += 1
            if caplen != _wirelen:
                continue
            if linktype == 127:
                if len(data) < 8 or data[0] != 0:
                    continue
                rtlen = int.from_bytes(data[2:4], "little")
                if rtlen < 8 or rtlen > len(data):
                    continue
                # Radiotap Flags is bit 1 in the first present word. TSFT
                # (bit 0) precedes it and is 8-byte aligned.
                present = int.from_bytes(data[4:8], "little")
                words_end = 8
                word = present
                while word & 0x80000000:
                    if words_end + 4 > rtlen:
                        raise ValueError("short radiotap present bitmap")
                    word = int.from_bytes(data[words_end:words_end + 4], "little")
                    words_end += 4
                flag_offset = words_end
                if present & 1:
                    flag_offset = (flag_offset + 7) & ~7
                    flag_offset += 8
                flags = data[flag_offset] if (present & 2 and flag_offset < rtlen) else 0
                data = data[rtlen:]
                fcs_present = bool(flags & 0x10)
                data_pad = bool(flags & 0x20)
            else:
                fcs_present = data_pad = False
            try:
                event = decode_mpdu(data, fcs_present=fcs_present,
                                    data_pad=data_pad, mesh_data=mesh_data)
            except ValueError:
                continue
            yield number, event
