# Raw-IQ PHY acceptance status

**Target:** receive-only IEEE 802.11ah IQ-to-MPDU decoding across 1, 2, 4, and
8 MHz, with the verified MPDU sent to this project's 802.11s MAC parser.
**Current result:** the four widths work on real Pi 5 captures in the modes
listed below. The receiver is suitable for offline analysis of those measured
modes. It is not yet a complete standards-conformant, real-time PHY receiver.

## What the receiver does

- Accepts signed 8-bit interleaved or complex IQ at an explicit sample rate,
  width, and channel-center offset. It checks Nyquist coverage and truncated
  input. The CLI scans a recording; GNU Radio accepts bounded IQ message PDUs
  or a complex sample stream segmented into overlapping windows.
- Detects S1G training fields, estimates timing and carrier offset, equalizes
  with the 1/2/4/8 MHz LTF, decodes SIG with CRC, BCC data and interleaver,
  descrambles the PSDU, and emits only MPDUs with a valid FCS.
- Supports `S1G_1M` at 1 MHz, including MCS10 repetition, and single-stream
  BCC `S1G_SHORT` at 2/4/8 MHz. Short GI and aggregation code paths exist but
  have not passed an independent over-air acceptance test. `S1G_LONG`, LDPC,
  multi-stream, NDP and 16 MHz are not decoded from IQ. The local MM6108
  supports a maximum 8 MHz channel, although 802.11ah defines 16 MHz.
- Keeps 802.11s protected data opaque. `mesh_decode` requires an explicit
  mesh-BSS context to interpret QoS Mesh Control.

## Measured over-air matrix

| Width | FCS-verified from independent HackRF IQ | Remaining local evidence |
| --- | --- | --- |
| 1 MHz | MCS0, MCS1, MCS10 broadcast probes | Other MCS and long payloads untested. |
| 2 MHz | MCS0 beacons, MCS1 probe | Other MCS untested. |
| 4 MHz | MCS0 and MCS3 probes | Other MCS untested. |
| 8 MHz | MCS0/1/2/3/5/6/7 probes; MCS0 mesh data | In a ten-probe MCS4/5 repeat, all target SIG fields decoded, two MCS5 MPDUs passed FCS, and five MCS4 MPDUs did not. A gain comparison found no matching target SIG. The local TX tool rejects MCS8/9. |

A synchronous private HackRF/MM6108 capture pair had 14 overlapping 8 MHz
MCS0 data frames and seven overlapping 2 MHz MCS0 beacons. Every one of those
21 raw-IQ decodes matched the separate MM6108 monitor's MPDU bytes, including
FCS. The broadcast probe frames at 1/2/4/8 MHz also passed FCS and matched
the preset body after accounting for the sequence number assigned by the TX
MAC. A valid SIG alone is never published as an MPDU.

A separately published 2 MHz IQ recording by Daniel Estévez provided an
additional external check. The first two seconds yielded 27 FCS-valid MPDUs;
all 27 matched exact bytes in the author's published decoded PCAP. Run
`tests/validate_public_iq.py` against the author's extracted ci16_le SigMF
data and PCAP to repeat this test. The two reference files are linked below
and are not included in this repository. The GNU Radio complex-stream block
also produced 27 exact matches on that two-second file. A private 8 MHz MCS7
frame crossing a 50 ms stream-window edge was emitted once at the correct
sample offset.

The field captures used a 10 Msps HackRF centered at 924 MHz and a Pi 5. The
radio was returned to PortaPack Mayhem mode, the MM6108 monitor and radiotap
interfaces were down, the injection gate was disabled, and the management
route remained on the Pi's built-in Wi-Fi after each run. Raw IQ, PCAP, and
device identifiers are stored only in restricted Atlas run directories.

## Remaining acceptance work

1. Independent conformance waveforms for every claimed MCS and width,
   `S1G_SHORT`/`S1G_1M` field variant, guard interval, aggregation, and
   malformed SIG/FCS. The local preset sender cannot exercise MCS8/9.
2. Measure packet error rate and false-alarm rate versus SNR, CFO, clock
   offset, multipath, clipping, adjacent-channel traffic, and payload size.
   Resolve the persistent 8 MHz MCS4 FCS failures and the MCS5 loss rate with
   a clean, independently received reference before declaring broad MCS4/5
   performance. Two MCS5 frames are verified; MCS4 is not.
3. Add `S1G_LONG`, LDPC, NDP, multi-stream, and 16 MHz only when the receiver
   implementation and independent test source actually support them. These
   are not silently accepted through fallback metadata.
4. Implement and benchmark sustained 10 Msps Pi 5 operation. The offline CLI
   processed a 4.2-second 8 MHz MCS matrix in 3.4 seconds at the sensitive
   default STF threshold, or 1.9 seconds at threshold .98. On a busy mesh
   recording it took 4.2 or 1.3 seconds per recorded second respectively.
   The higher threshold preserved all six verified matrix frames but has not
   been sensitivity-tested for weak frames. The GNU Radio stream block uses
   overlapping bounded windows inside its work thread. The public two-second
   stream test took 3.75 seconds on this Pi. Hardware overrun detection and
   lossless live flow control remain unimplemented.

## Sources and provenance

- [IEEE 802.11ah decoding analysis by Daniel Estévez](https://destevez.net/2025/01/decoding-ieee-802-11ah/) and the linked MIT-licensed notebook supply the 2 MHz training, synchronization, SIG, and BCC basis.
- [Estévez's published IQ archive](https://nas.destevez.net/~daniel/IEEE_802.11ah/) and [decoded PCAP](https://github.com/daniestevez/jupyter_notebooks/blob/master/IEEE_802.11ah/802_11_ah.pcap) supply the external 2 MHz acceptance pair.
- [gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) is a GPL-3.0-or-later 1 MHz implementation used to cross-check S1G_1M LTF and SIG repetition/interleaving.
- The [IEEE TGah specification framework](https://ie.u-ryukyu.ac.jp/~wada/system15/11-11-1137-15-00ah-specification-framework-for-tgah%20(2).pdf) and [Keysight 802.11ah signal configuration](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Signal%20Configuration.htm) describe format and width choices.
- See `THIRD_PARTY_NOTICES.md` for software attribution and license terms.
