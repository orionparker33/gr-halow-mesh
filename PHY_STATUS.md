# Raw-IQ PHY acceptance status

**Target:** receive-only IEEE 802.11ah IQ-to-MPDU decoding across 1, 2, 4, and
8 MHz, with the verified MPDU sent to this project's 802.11s MAC parser.
**Current result:** the four widths work on real Pi 5 captures in the modes
listed below. The receiver is suitable for offline analysis of those measured
modes. It is not yet a complete standards-conformant, real-time PHY receiver.

## What the receiver does

- Accepts signed 8-bit interleaved or complex IQ at an explicit sample rate,
  width, and channel-center offset. It checks Nyquist coverage and truncated
  input. The CLI scans a recording and the GNU Radio block accepts bounded IQ
  message PDUs.
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
| 8 MHz | MCS0/1/2/3/6/7 probes; MCS0 mesh data | MCS4/5 SIG decoded on one probe each, but payload FCS failed. The follow-up capture showed no matching target SIG amid other traffic. The local TX tool rejects MCS8/9. |

A synchronous private HackRF/MM6108 capture pair had 14 overlapping 8 MHz
MCS0 data frames and seven overlapping 2 MHz MCS0 beacons. Every one of those
21 raw-IQ decodes matched the separate MM6108 monitor's MPDU bytes, including
FCS. The broadcast probe frames at 1/2/4/8 MHz also passed FCS and matched
the preset body after accounting for the sequence number assigned by the TX
MAC. A valid SIG alone is never published as an MPDU.

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
   Resolve the observed 8 MHz MCS4/5 FCS failures with a clean, independently
   received reference before marking those combinations verified.
3. Add `S1G_LONG`, LDPC, NDP, multi-stream, and 16 MHz only when the receiver
   implementation and independent test source actually support them. These
   are not silently accepted through fallback metadata.
4. Implement and benchmark sustained 10 Msps Pi 5 operation. The current
   offline CLI processed one 4.2-second 8 MHz mixed-width capture in 6.8
   seconds. GNU Radio integration currently accepts bounded IQ PDUs; it does
   not expose a continuous stream block or flow-control guarantee.

## Sources and provenance

- [IEEE 802.11ah decoding analysis by Daniel Estévez](https://destevez.net/2025/01/decoding-ieee-802-11ah/) and the linked MIT-licensed notebook supply the 2 MHz training, synchronization, SIG, and BCC basis.
- [gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) is a GPL-3.0-or-later 1 MHz implementation used to cross-check S1G_1M LTF and SIG repetition/interleaving.
- The [IEEE TGah specification framework](https://ie.u-ryukyu.ac.jp/~wada/system15/11-11-1137-15-00ah-specification-framework-for-tgah%20(2).pdf) and [Keysight 802.11ah signal configuration](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Signal%20Configuration.htm) describe format and width choices.
- See `THIRD_PARTY_NOTICES.md` for software attribution and license terms.
