# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, receive-only 802.11ah/802.11s MAC parsing.

Input is a recovered MPDU, without radiotap. This module performs no PHY
demodulation, decryption, packet injection, or mesh state mutation.
"""

import struct
import zlib


def _mac(value):
    return ":".join(f"{b:02x}" for b in value)


def _ies(data):
    result = []
    at = 0
    while at < len(data):
        if at + 2 > len(data):
            raise ValueError("truncated information element header")
        eid, length = data[at], data[at + 1]
        at += 2
        if at + length > len(data):
            raise ValueError("truncated information element body")
        result.append((eid, data[at:at + length]))
        at += length
    return result


def _mesh_ies(event, ies):
    for eid, value in ies:
        if eid == 114 and len(value) <= 32:
            event["mesh"] = True
            event["mesh_id"] = value.decode("utf-8", "replace")
        elif eid == 113 and len(value) == 7:
            event["mesh"] = True
            event["mesh_config"] = {
                "path_protocol": value[0], "path_metric": value[1],
                "congestion_control": value[2], "synchronization": value[3],
                "authentication": value[4],
                "peer_count": (value[5] >> 1) & 0x3f,
                "connected_to_gate": bool(value[5] & 1),
                "accepting_peerings": bool(value[6] & 1),
                "forwarding": bool(value[6] & 8),
            }
        elif eid == 117 and len(value) >= 4:
            event["mesh"] = True
            event["peer_management"] = {
                "protocol": int.from_bytes(value[:2], "little"),
                "local_link_id": int.from_bytes(value[2:4], "little"),
                "length": len(value),
            }
        elif eid in (126, 130, 131, 132):
            event["mesh"] = True
            event.setdefault("hwmp_elements", []).append({"id": eid, "length": len(value)})


def decode_mpdu(frame, *, fcs_present=False, data_pad=False, mesh_data=False):
    """Return conservative mesh metadata from a recovered 802.11 MPDU.

    Raises ValueError on malformed, truncated, or bad-FCS input. The parser
    deliberately leaves protected payload bytes opaque.
    """
    frame = bytes(frame)
    if len(frame) > 65535:
        raise ValueError("oversize MPDU")
    if fcs_present:
        if len(frame) < 8:
            raise ValueError("truncated FCS frame")
        expected = int.from_bytes(frame[-4:], "little")
        if zlib.crc32(frame[:-4]) != expected:
            raise ValueError("bad FCS")
        frame = frame[:-4]
    if len(frame) < 10:
        raise ValueError("short MPDU")
    fc = int.from_bytes(frame[:2], "little")
    version, kind, subtype = fc & 3, (fc >> 2) & 3, (fc >> 4) & 15
    if version:
        raise ValueError("unsupported protocol version")
    event = {"mesh": False, "frame_type": kind, "subtype": subtype,
             "protected": bool(fc & 0x4000), "to_ds": bool(fc & 0x0100),
             "from_ds": bool(fc & 0x0200), "receiver": _mac(frame[4:10])}
    if kind == 3 and subtype == 1:  # S1G beacon: 10-byte header, 5 fixed bytes
        if len(frame) < 15:
            raise ValueError("short S1G beacon")
        event["kind"] = "s1g_beacon"
        event["transmitter"] = event.pop("receiver")
        event.pop("protected")
        event["security_supported"] = bool(fc & 0x4000)
        _mesh_ies(event, _ies(frame[15:]))
        return event
    if kind == 0:
        if len(frame) < 24:
            raise ValueError("short management header")
        event["transmitter"] = _mac(frame[10:16])
        event["kind"] = "management"
        if subtype in (5, 8):  # probe response and beacon
            if len(frame) < 36:
                raise ValueError("short beacon fixed fields")
            _mesh_ies(event, _ies(frame[36:]))
        elif subtype == 13:  # action frame
            if len(frame) < 26:
                raise ValueError("short action frame")
            category, action = frame[24:26]
            event["action_category"] = category
            event["action_code"] = action
            if category == 13 and action == 1:
                event["mesh"] = True
                event["kind"] = "hwmp_action"
                _mesh_ies(event, _ies(frame[26:]))
            elif category == 15 and action in (1, 2, 3):
                event["mesh"] = True
                event["kind"] = ("peer_open", "peer_confirm", "peer_close")[action - 1]
                # Peering actions have fixed fields before their IEs; do not
                # guess offsets or parse opaque bytes as IEs.
        return event
    if kind == 2:
        if len(frame) < 24:
            raise ValueError("short data header")
        event["kind"] = "data"
        event["transmitter"] = _mac(frame[10:16])
        at = 30 if (fc & 0x0300) == 0x0300 else 24
        if len(frame) < at:
            raise ValueError("short four-address data header")
        if subtype & 8:
            if len(frame) < at + 2:
                raise ValueError("short QoS header")
            qos = int.from_bytes(frame[at:at + 2], "little")
            at += 2
            if fc & 0x8000:
                at += 4
            # QoS bit 8 has different meaning outside a mesh BSS. Require
            # the caller to establish mesh context before interpreting it.
            if mesh_data and qos & 0x0100:
                if event["protected"]:
                    event["mesh"] = True
                    event["mesh_control_encrypted"] = True
                    return event
                if data_pad:
                    at = (at + 3) & ~3
                if len(frame) < at + 6:
                    raise ValueError("short mesh control")
                flags = frame[at]
                ae = flags & 3
                extra = 6 if ae == 1 else 12 if ae in (2, 3) else 0
                if len(frame) < at + 6 + extra:
                    raise ValueError("short mesh address extension")
                event["mesh"] = True
                event["mesh_control"] = {
                    "flags": flags, "ttl": frame[at + 1],
                    "sequence": struct.unpack_from("<I", frame, at + 2)[0],
                    "address_extension": ae,
                }
                if extra:
                    event["mesh_control"]["extra_addresses"] = [
                        _mac(frame[i:i + 6]) for i in range(at + 6, at + 6 + extra, 6)]
        return event
    event["kind"] = "other"
    return event
