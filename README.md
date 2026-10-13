# gr-halow-mesh

GNU Radio message blocks and PCAP adapter for receive-only analysis of IEEE
802.11ah (Wi-Fi HaLow) and IEEE 802.11s mesh MAC frames. This is a MAC parser:
it accepts recovered 802.11 MPDUs and emits structured mesh events. It does
not demodulate IQ itself or decrypt protected payloads.

## Receive paths

```text
1 MHz IQ -> gr-ieee802-11ah PHY/decode_mac -> MPDU PDU -> mesh_decode
HaLow monitor radio -> radiotap PCAP -> pcap_source -> mesh_decode
                                    \-> halow_mesh_pcap.py
ordinary Wi-Fi monitor PCAP -------> halow_mesh_pcap.py
```

The 1 MHz IQ path uses the separate
[gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) GNU Radio
module. It has a CRC-checked, FCS-stripped MPDU PDU output compatible with
this project's `in` port. Wider HaLow channels need another PHY receiver.
The MM6108 monitor radio has been validated at an 8 MHz operating width with
a 2 MHz primary channel; its PCAP runs through the GNU Radio PCAP source and
mesh decoder. An independent 8 MHz IQ receiver is not included. The engineering and
validation gates for that production target are tracked in `PHY_STATUS.md`.

The GRC block **HaLow / 802.11s Mesh Decode** has message input `in` and
outputs `out` and `events`. `out` preserves the MPDU and adds a
`halow_mesh_json` UTF-8 u8vector to its metadata. `events` carries a JSON
u8vector PDU. By default, only mesh frames are emitted. Set **Emit ordinary
frames** to include all supported MPDUs.

The GRC block **HaLow / 802.11s PCAP Source** reads classic radiotap or raw
802.11 PCAP once and publishes recovered MPDUs to its `out` message port.
Connect it to the decoder's `in` port. Radiotap FCS and data-padding flags
are carried in PDU metadata, so the decoder checks advertised FCS.

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

GNU Radio 3.10, Python 3, NumPy, and SciPy are required. On Debian-based systems, install
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
`GRC_BLOCKS_PATH` to that directory **and** the system block path. Offline GRC examples are in `examples/mesh_message_demo.grc` and
`examples/mesh_pcap_demo.grc`. Set the latter source block path to a PCAP.
The graph runs once; the source publishes every record and then stops emitting.

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

## Raw-IQ development diagnostic

`halow_iq_probe.py` inspects a short signed-8-bit I/Q window for cyclic-prefix
correlation at the 32 µs S1G useful-symbol duration. Select 1, 2, 4, 8, or
16 MHz with `--bandwidth-mhz` and optionally shift the channel center with
`--offset-hz`; the tool filters that channel and reports the original IQ
energy fraction it contained. It removes local DC bias and reports FFT spread
so a narrow tone is distinguishable from wideband OFDM. For example, at 10 Msps:

```bash
halow_iq_probe.py PRIVATE_CAPTURE.cs8 --sample-rate 10000000 \
  --bandwidth-mhz 8 \
  --start 0.7933 --duration-ms 4
```

This is a diagnostic, **not a PHY decoder or packet detector**. A strong
correlation and many occupied FFT bins can be caused by other OFDM signals;
only S1G SIG and FCS validation can identify a HaLow frame. The command reads
the requested window without changing a radio. At least 20 Msps is needed to
inspect a centered 16 MHz channel with this tool. The local MM6108 monitor
radio supports only 1/2/4/8 MHz, so 16 MHz analysis has no hardware reference
here and is unverified.

## Verification and scope

Parser, PCAP-source, and message-port integration tests run with CTest. The GRC example
compiles under GNU Radio 3.10. A private two-node HaLow monitor capture was
cross-checked against TShark: the parser matched all 85 mesh-advertising S1G
beacons and correctly withheld a mesh-data classification from 420 protected
QoS frames without mesh-BSS context. An over-the-air 1 MHz IQ-to-MPDU run and
independent wider-channel IQ decoding are not yet verified by this project.
The GNU Radio PCAP-source to mesh-decoder graph yielded 85 mesh beacons from
the first 8 MHz monitor capture and all five from a second 8 MHz capture.

The code is licensed GPL-3.0-or-later; see `LICENSE`. It is not affiliated
with the Meshtastic project, which uses LoRa rather than IEEE 802.11ah.
