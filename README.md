# gr-halow-mesh

GNU Radio message block and PCAP adapter for receive-only analysis of IEEE
802.11ah (Wi-Fi HaLow) and IEEE 802.11s mesh MAC frames. This is a MAC parser:
it accepts recovered 802.11 MPDUs and emits structured mesh events. It does
not demodulate IQ itself or decrypt protected payloads.

## Receive paths

```text
1 MHz IQ -> gr-ieee802-11ah PHY/decode_mac -> MPDU PDU -> mesh_decode
HaLow monitor radio -> radiotap PCAP -> halow_mesh_pcap.py
ordinary Wi-Fi monitor PCAP -------> halow_mesh_pcap.py
```

The 1 MHz IQ path uses the separate
[gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) GNU Radio
module. It has a CRC-checked, FCS-stripped MPDU PDU output compatible with
this project's `in` port. Wider HaLow channels need another PHY receiver,
such as a monitor-mode HaLow radio. An independent 8 MHz IQ receiver is not
included.

The GRC block **HaLow / 802.11s Mesh Decode** has message input `in` and
outputs `out` and `events`. `out` preserves the MPDU and adds a
`halow_mesh_json` UTF-8 u8vector to its metadata. `events` carries a JSON
u8vector PDU. By default, only mesh frames are emitted. Set **Emit ordinary
frames** to include all supported MPDUs.

## Decoded fields

- S1G beacon and ordinary beacon/probe response Mesh ID (IE 114) and Mesh
  Configuration (IE 113), including peer count and advertised capabilities.
- Mesh peering action type and a bounded Peer Management IE summary.
- HWMP action type and PREQ/PREP/PERR/RANN IE identifiers and lengths.
- Mesh Control flags, TTL, sequence, and address extensions for unprotected
  QoS data when **Input is a mesh BSS** is explicitly enabled.

QoS bit 8 is reused outside a mesh BSS. The parser therefore never treats it
as Mesh Control Present without mesh-BSS context supplied by the caller.
Protected data remains opaque; enabling the mesh-BSS option reports only that
Mesh Control is indicated, not its encrypted contents. Advertisement does not
prove peer establishment or routing success.

## Build

GNU Radio 3.10 and Python 3 are required. On Debian-based systems, install
the GNU Radio development package and Python bindings. Build and test:

```bash
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr/local \
  -DGR_PYTHON_DIR=lib/python3.13/dist-packages
cmake --build build
ctest --test-dir build --output-on-failure
sudo cmake --install build
```

Change `python3.13` to the target host's Python ABI directory. CMake installs
the block in GNU Radio's Python namespace and its YAML in the GRC block tree.
If GRC does not discover `/usr/local/share/gnuradio/grc/blocks`, set
`GRC_BLOCKS_PATH` to that directory **and** the system block path. A small
offline GRC example is in `examples/mesh_message_demo.grc`.

## PCAP adapter

```bash
halow_mesh_pcap.py capture.pcap
halow_mesh_pcap.py capture.pcap --all
halow_mesh_pcap.py known-mesh-bss.pcap --mesh-data
```

The adapter accepts classic PCAP linktype 127 (radiotap) or 105 (raw 802.11),
handles radiotap FCS and data-padding flags, and prints one JSON event per
selected frame. Unsupported, malformed, and driver-specific NDP records are
skipped. `--mesh-data` must only be used when the capture is known to be from
a mesh BSS; this is not inferred from frequency or nearby beacons.

## Verification and scope

Parser and message-port integration tests run with CTest. The GRC example
compiles under GNU Radio 3.10. A private two-node HaLow monitor capture was
cross-checked against TShark: the parser matched all 85 mesh-advertising S1G
beacons and correctly withheld a mesh-data classification from 420 protected
QoS frames without mesh-BSS context. An over-the-air 1 MHz IQ-to-MPDU run and
independent wider-channel IQ decoding are not yet verified by this project.

The code is licensed GPL-3.0-or-later; see `LICENSE`. It is not affiliated
with the Meshtastic project, which uses LoRa rather than IEEE 802.11ah.
