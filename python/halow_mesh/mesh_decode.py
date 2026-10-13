# SPDX-License-Identifier: GPL-3.0-or-later
"""Message-only GNU Radio decoder for recovered 802.11 mesh MPDUs."""

import json

import pmt
from gnuradio import gr

from .protocol import decode_mpdu


class mesh_decode(gr.basic_block):
    """Accept (metadata, raw MPDU) PDUs and emit mesh events as JSON PDUs.

    The ``out`` port preserves the MPDU and adds ``halow_mesh_json`` to its
    metadata. The ``events`` port contains UTF-8 JSON. Neither port emits an
    event for an ordinary non-mesh frame unless ``emit_all`` is enabled.
    """

    def __init__(self, emit_all=False, mesh_data=False):
        super().__init__(name="mesh_decode", in_sig=None, out_sig=None)
        self.emit_all = bool(emit_all)
        self.mesh_data = bool(mesh_data)
        self.message_port_register_in(pmt.intern("in"))
        self.message_port_register_out(pmt.intern("out"))
        self.message_port_register_out(pmt.intern("events"))
        self.set_msg_handler(pmt.intern("in"), self._handle)

    def _handle(self, message):
        if not pmt.is_pair(message):
            return
        metadata, payload = pmt.car(message), pmt.cdr(message)
        if pmt.is_u8vector(payload):
            frame = bytes(pmt.u8vector_elements(payload))
        elif pmt.is_blob(payload):
            frame = bytes(pmt.to_python(payload))
        else:
            return
        try:
            event = decode_mpdu(frame, mesh_data=self.mesh_data)
        except ValueError:
            return
        if not (event["mesh"] or self.emit_all):
            return
        encoded = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        if not pmt.is_dict(metadata):
            metadata = pmt.make_dict()
        json_vector = pmt.init_u8vector(len(encoded), list(encoded))
        metadata = pmt.dict_add(metadata, pmt.intern("halow_mesh_json"), json_vector)
        self.message_port_pub(pmt.intern("out"), pmt.cons(metadata, payload))
        self.message_port_pub(pmt.intern("events"),
                              pmt.cons(pmt.make_dict(), json_vector))
