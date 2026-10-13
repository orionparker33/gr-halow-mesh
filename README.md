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
`S1G_1M` at 1 MHz, `S1G_SHORT` at 2/4/8 MHz, and `S1G_LONG` single-user
frames at 2 MHz. The 1 MHz path includes
MCS10 repetition. Code paths for MCS0–7 (and MCS8/9 above 1 MHz) are present;
see [PHY_STATUS.md](PHY_STATUS.md) for independently verified combinations and
[FORMAT_GAP_RESEARCH.md](FORMAT_GAP_RESEARCH.md) for format-specific closure
tests and independent vector sources.
Wider `S1G_LONG`, LDPC, multi-stream PPDUs, and NDP are outside this IQ receiver.
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
overwrite an existing one; an incomplete PCAP is removed if decoding fails.
`--workers 0` selects up to four Pi cores for a capture with at least 128
coarse candidates; `--workers 1` gives a serial comparison. Candidate windows
retain up to 200 ms of IQ at 2/4/8 MHz, or 30 ms at 1 MHz by default;
`--max-ppdu-ms` sets an explicit 1–200 ms bound. Payload IQ is channelized
only after the preamble and SIG pass their checks. The optional
`--stf-threshold` raises the coarse preamble threshold above the sensitive
default of 0.75. A high threshold can miss weak packets. At 8 MHz,
`--max-subband-fraction .8` can reject narrowband preamble impostors, but it
can also miss a weak 8 MHz frame masked by strong narrowband interference;
the default `1` leaves that filter disabled.

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
At 8 MHz, when more candidates occur than the configured cap, the block
prefers candidates whose short spectrum fills the wide channel. This ranking
does not replace SIG CRC or MPDU FCS.
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
MCS0–7, 4 MHz MCS0–7, and 8 MHz MCS0–7. The prior 2 MHz
MCS2/4/5/6/7 failures were caused by an aliased STF timing estimate; a bounded
FCS-gated timing search recovered all five from their original IQ. Twenty-one
overlapping 2/8 MHz frames matched an independent MM6108 monitor capture byte
for byte. A bounded 2 MHz guard-interval trial recovered two long-GI and two
short-GI MCS1 broadcast probes with valid FCS and the expected frame body.
The independent HackRF receiver did not recover the third submitted short-GI
probe; this is one bounded trial, not a packet-error-rate measurement.

At 8 MHz, an initially all-fail MCS4/5 run clipped about 66% of active IQ
samples. A repeat at zero receiver gain recovered one FCS-valid MCS4 and one
MCS5 probe. At intermediate gain, the ordinary CLI recovered one MCS4 and two
MCS5 frames after input resampling phase was aligned to the absolute sample
offset. All recovered bodies matched the rendered presets. Three of six
submitted intermediate-gain probes still failed FCS, so packet-loss
performance is not accepted. A longer non-clipping 916 MHz capture contained
all 30 planned MCS4/5 preambles with CRC-valid SIGs, but the decoder recovered
only 1/15 MCS4 and 8/15 MCS5 FCS-valid MPDUs. Several failed MCS5 payloads
had the expected body and errors only in the FCS bytes. Pilot, channel-weight,
and Viterbi diagnostic variants did not improve the result; the installed
receiver was unchanged. The local TX tool rejects
MCS8/9, so those are not over-air validated. The first two seconds of
Daniel Estévez's separately published 2 MHz IQ recording yielded 116
FCS-valid MPDUs, including 55 `S1G_LONG` frames; all 116 exactly matched the
published PCAP. The GNU Radio stream graph emitted 115 exact matches from
the same windowed recording. A separate 8 MHz MCS7
frame crossing a window edge was emitted once. After channel selection, the
stream block recovered all nine real 1 MHz MCS0–7/10 probes and all eight
4 MHz MCS0–7 probes. A complete 8 MHz IQ stream-to-mesh graph emitted four
mesh events from two seconds of the synchronized local recording.
`tests/validate_public_iq.py` repeats the offline comparison when
given the author's extracted ci16_le SigMF data and PCAP; neither is bundled.
In a 30-second synchronized 8 MHz mesh capture, the sensitive default CLI
recovered 58 of 58 monitor-referenced data MPDUs with exact bytes and no
additional frames; the same IQ yielded 30 of 30 monitor beacons at 2 MHz.
With four Pi 5 workers, 30 seconds of 8 MHz IQ took 17.2 seconds offline
after loading only the needed preamble and payload slices. The older
single-core path took 50.6 seconds. A separate optional narrowband filter
was also checked against all 58 frames, but is not needed for this offline
rate. A GNU Radio complex-file replay of the same 30-second IQ took 14.0
seconds and emitted the same 58 MPDUs byte for byte after wideband candidate
ranking. This does not establish lossless live capture: the stream block
still decodes in its work thread and exposes no structured hardware drop
counter. A bounded live HackRF/OsmoSDR run with the source's default ring
reported 38 overflow markers; a repeat with `hackrf=0,buffers=512` reported
zero and captured 299.5 million complex samples in 30 seconds. That repeat
emitted 55 FCS-valid MPDUs, all 55 exact independent MM6108 monitor matches,
while the monitor saw 59 data MPDUs in the graph interval. A further live
trial also had zero overflow markers, but the RF signal and independent
monitor count changed substantially, so it cannot establish a gain or
packet-error improvement. These results do not qualify the live path as
lossless or establish its sensitivity. See
[PHY_STATUS.md](PHY_STATUS.md) for the acceptance matrix and remaining work.

The code is GPL-3.0-or-later; see [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). It is not affiliated with
Meshtastic, which uses LoRa rather than IEEE 802.11ah.
