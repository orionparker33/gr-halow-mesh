# gr-halow-mesh

Receive-only GNU Radio and Python tools for IEEE 802.11ah (Wi-Fi HaLow) IQ and
IEEE 802.11s mesh MAC analysis. The raw-IQ receiver emits an MPDU only after
its 802.11 FCS passes. It never transmits or decrypts protected payloads.

## Receive paths

```text
signed-byte IQ file --> halow_iq_decode.py --> FCS-verified radiotap PCAP
bounded IQ PDU ------> HaLow S1G IQ Decode --> HaLow / 802.11s Mesh Decode
complex IQ stream ---> HaLow S1G IQ Stream Decode --> Mesh Decode
HaLow monitor PCAP --> HaLow / 802.11s PCAP Source --> Mesh Decode
ordinary Wi-Fi PCAP -------------------------> halow_mesh_pcap.py
```

Choose **1, 2, 4, or 8 MHz** and the channel-center offset explicitly. The
local MM6108 supports up to 8 MHz. IEEE 802.11ah also defines 16 MHz, which
this receiver does not decode. The IQ path supports single-stream BCC
`S1G_1M` at 1 MHz and `S1G_SHORT` at 2/4/8 MHz. The 1 MHz path includes
MCS10 repetition. Code paths for MCS0–7 (and MCS8/9 above 1 MHz) are present;
see [PHY_STATUS.md](PHY_STATUS.md) for independently verified combinations.
`S1G_LONG`, LDPC, multi-stream PPDUs, and NDP are outside this IQ receiver.
The MM6108 monitor/PCAP path can still observe formats that its firmware
decodes. IEEE 802.11s is a MAC mesh mode, so its frames use the ordinary Wi-Fi
PHY on their operating band.

## Decode a recording

The CLI accepts interleaved signed 8-bit I/Q (the `hackrf_transfer` `.cs8`
format). The sample rate must cover the selected channel and offset. For a
10 Msps recording centered at 924 MHz, examples are:

```bash
halow_iq_decode.py capture.cs8 --sample-rate 10000000 \
  --bandwidth-mhz 8 --offset-hz 0
halow_iq_decode.py capture.cs8 --sample-rate 10000000 \
  --bandwidth-mhz 1 --offset-hz -1500000
```

The second command selects a 1 MHz channel centered at 922.5 MHz. Each JSON
line reports the IQ sample offset, width, MCS, PPDU format, CFO estimate, and
FCS result. To export a radiotap PCAP, provide the UTC time of IQ sample zero:

```bash
halow_iq_decode.py capture.cs8 --sample-rate 10000000 \
  --bandwidth-mhz 8 --start-utc 2026-10-13T05:25:00Z \
  --pcap verified.pcap
halow_mesh_pcap.py verified.pcap --all
```

The CLI scans bounded candidate windows; it does not assert that silence or a
missing frame means an idle channel. A recorded sample clock and center
frequency must be accurate enough to cover the signal. Keep raw IQ and PCAP
from assessments private. `--pcap` creates a new mode-0600 file and refuses to
overwrite an existing one. The optional `--stf-threshold` raises the coarse
preamble threshold above the sensitive default of 0.75. A high threshold can
speed up a busy recording but can miss weak packets.

## GNU Radio IQ blocks

The GRC block **HaLow S1G IQ Decode** accepts a bounded IQ PDU on `in` with a
`c32vector` of complex samples or a `u8vector` of interleaved signed-byte IQ.
Set sample rate, width, and offset in the block. An optional integer
`sample_offset` in the input metadata is added to each emitted MPDU's offset.
The output `out` is a u8vector MPDU PDU with `fcs_present`, `fcs_ok`, `mcs`,
`bandwidth_mhz`, `ppdu_format`, `cfo_hz`, and `sample_offset` metadata. Connect
it to **HaLow / 802.11s Mesh Decode**. The block expects a caller to segment
an IQ stream into windows that contain the complete PPDU; it is a message
block.

The **HaLow S1G IQ Stream Decode** block accepts a continuous complex32
stream, divides it into overlapping bounded windows, and emits the same
FCS-verified MPDU PDUs. Its default 100 ms window and 30 ms overlap preserve
supported frames crossing a window edge; its output `sample_offset` is
relative to stream sample zero. Connect its `out` message port to **HaLow /
802.11s Mesh Decode**. A raw preamble threshold and maximum candidate count
bound the search per window. Raising the threshold reduces work on busy
channels but may miss weak frames; a low candidate cap may drop frames in a
dense window. At exactly 1 Msps for 1 MHz, or 4 Msps for 4 MHz, the block
uses full-window detection; this avoids a frequency-shifted SDR center spur
flooding the coarse preamble candidate list.
It decodes inside the GNU Radio work thread and has no hardware-overrun
detection or sustained real-time guarantee.

The **HaLow / 802.11s PCAP Source** block accepts classic radiotap or raw
802.11 PCAP and publishes recovered MPDUs to `out`. It can feed the same mesh
decoder without SDR hardware. Radiotap FCS and data-padding flags are
preserved in PDU metadata.

## Mesh MAC output

**HaLow / 802.11s Mesh Decode** accepts recovered MPDUs on `in` and emits
annotated MPDUs on `out` and JSON event PDUs on `events`. It reports:

- S1G and ordinary beacon/probe Mesh ID and Mesh Configuration elements.
- Mesh peering and HWMP action types, with bounded IE summaries.
- Mesh Control flags, TTL, sequence, and address extensions for unprotected
  QoS data when **Input is a mesh BSS** is explicitly enabled.

QoS bit 8 is reused outside mesh BSSs. The parser does not infer mesh context
from nearby beacons or frequency. Protected payloads stay opaque; an advertised
Mesh ID or peer count does not prove peering or routing success.

The command-line PCAP adapter is available independently:

```bash
halow_mesh_pcap.py capture.pcap --all
halow_mesh_pcap.py known-mesh-bss.pcap --mesh-data
```

## Build and test

GNU Radio 3.10, Python 3, NumPy, SciPy, and Python development headers are
required. The small C extension accelerates the BCC Viterbi decoder. On a
Debian-style GNU Radio 3.10/Python 3.13 host:

```bash
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr/local \
  -DGR_PYTHON_DIR=lib/python3.13/dist-packages
cmake --build build
ctest --test-dir build --output-on-failure
sudo cmake --install build
```

Adjust the Python ABI path for another host. GRC definitions install under
`/usr/local/share/gnuradio/grc/blocks`. If GRC does not discover that path,
add it to `GRC_BLOCKS_PATH` alongside the system block directory. Offline
message and PCAP examples are in `examples/`.
`examples/iq_message_demo.py` feeds one bounded IQ file window through the
IQ and mesh GNU Radio message blocks. `examples/mesh_iq_stream_demo.grc`
shows a complex32 file source feeding the continuous IQ block and mesh
decoder; set its file path, sample rate, width, and offset before running it.
The published-capture acceptance command is
`python3 tests/validate_public_iq.py DATA.sigmf-data 802_11_ah.pcap --stream`
after extracting the author's 3.84 Msps ci16_le data from the linked archive.

## Validation and limits

On the Pi 5, real IQ yielded FCS-valid MPDUs at 1 MHz MCS0–7/10, 2 MHz
MCS0/1/3, 4 MHz MCS0–7, and 8 MHz MCS0/1/2/3/5/6/7. Twenty-one overlapping
2/8 MHz frames matched an independent MM6108 monitor capture byte for byte.
The first 8 MHz MCS4/5 probes had valid SIG fields but failed FCS. In a
bounded repeat, all ten target SIG fields appeared and two MCS5 MPDUs passed
FCS; none of the five MCS4 MPDUs passed FCS. A later gain comparison captured
no matching target SIG and did not settle MCS4. The local
TX tool rejects MCS8/9, so those are not over-air validated. No production
claim is made for unsupported formats or untested MCS/guard-interval/FEC
combinations. A bounded 2/4 MHz matrix gave valid SIG for all eight modes
per width and FCS-valid 4 MHz MCS0–7, but 2 MHz MCS2/4/5/6/7 failed FCS.
The first two seconds of Daniel Estévez's separately published 2 MHz IQ
recording yielded 50 FCS-valid MCS1 MPDUs, all exact matches to the published
PCAP both offline and in the GNU Radio stream graph. A separate 8 MHz MCS7
frame crossing a window edge was emitted once. After channel selection, the
stream block recovered all nine real 1 MHz MCS0–7/10 probes and all eight
4 MHz MCS0–7 probes. A complete 8 MHz IQ stream-to-mesh graph emitted four
mesh events from two seconds of the synchronized local recording.
`tests/validate_public_iq.py` repeats the offline comparison when
given the author's extracted ci16_le SigMF data and PCAP; neither is bundled.
On this Pi 5, a 4.2-second local 8 MHz MCS matrix took 3.4 seconds to scan
at the default threshold and 1.9 seconds with `--stf-threshold .98`. A busy
one-second mesh recording took 4.2 and 1.3 seconds respectively. These are
offline measurements, not a sustained real-time guarantee. The optimized
stream graph processed the 4.168-second 8 MHz MCS matrix in 4.14 seconds on
this Pi and recovered all six verified frames at the default raw-preamble
threshold. This does not establish lossless live capture. See
[PHY_STATUS.md](PHY_STATUS.md) for the acceptance matrix and remaining work.

The code is GPL-3.0-or-later; see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). It is not affiliated with
Meshtastic, which uses LoRa rather than IEEE 802.11ah.
