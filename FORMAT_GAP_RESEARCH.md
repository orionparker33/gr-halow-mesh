# 802.11ah format gaps: evidence and closure plan

Scope: raw-IQ receive through 8 MHz and handoff to the existing 802.11s MAC
parser. The operator deferred 16 MHz. A decoded SIG CRC is evidence of a PHY
candidate; only an independently checked MPDU FCS proves a recovered data
frame. NDP has no MPDU/FCS and needs a separate, explicitly typed event.

This document distinguishes a known standard feature, an implemented path,
and a tested path. It does not promote a feature to supported merely because
the receiver has a branch for it. IEEE P802.11ah/D0.1 is an early draft used
for field research, not a substitute for the published standard.

## Independent vector sources found

| Source | Suitable cases | Limit |
| --- | --- | --- |
| [MathWorks `wlanS1GConfig`](https://www.mathworks.com/help/wlan/ref/wlans1gconfig.html) and [waveform generator](https://www.mathworks.com/help/wlan/ref/wlanwaveformgenerator.html) | BCC short/long, 1/2/4/8 MHz, MCS8/9, short GI, SU/MU, STBC and spatial mapping; `APEPLength=0` gives an [NDP waveform](https://www.mathworks.com/help/wlan/ref/wlanfieldindices.html). | The S1G configuration's `ChannelCoding` is read-only `BCC`. An `APEPLength=0` sounding NDP is not automatically an NDP MAC subtype fixture. The Pi has no MATLAB installation or licensed vector export. |
| [Keysight 802.11ah advanced waveform mode](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Waveform%20Setup.htm) | Fully channel-coded MPDUs, LDPC, MU, [NDP MAC and sounding NDP](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Waveform%20Setup.htm), and [multi-member A-MPDU](https://helpfiles.keysight.com/csg/n7617/Content/Main/802.11ah%20User%20Basic.htm). | Requires access to that software/instrument and exported complex IQ plus exact expected payloads. Its basic mode omits LDPC, MU and MPDU setup. Documentation alone is not a validation vector. |
| [Estévez public 2 MHz IQ and PCAP](https://destevez.net/2025/01/decoding-ieee-802-11ah/) | Real BCC short and single-user long frames, including high MCS, traveling pilots and aggregation. | Does not cover 4/8 MHz long, NDP MAC, LDPC, spatial streams or MCS8/9. |
| [gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) | Independent 1 MHz MCS0/1/10 recordings and a GNU Radio 1 MHz transceiver. | Its stated scope is 1 MHz. Do not infer wider or optional-format coverage. |

For a reusable conformance corpus, preserve complex sample format/rate and
center offset, TXVECTOR or equivalent configuration, exact expected MPDU
bytes or NDP SIG fields, per-frame timestamp, source/version, and a cryptographic
hash. Separate clean baseband vectors from independent over-air captures.

## S1G_LONG, including wide single-user and multi-user

The [S1G PPDU structure](https://www.mathworks.com/help/wlan/gs/s1g-ppdu-structure.html)
places omnidirectional SIG-A before D-STF, D-LTF, SIG-B and data. A single-user
SIG-B repeats D-LTF1; a multi-user SIG-B carries per-user information. The
2 MHz single-user implementation has 55 exact published IQ/PCAP matches.

For 4/8 MHz single-user, reuse the verified SIG-A parser and full-band LTF
geometry, then estimate the beam-changeable channel from every full-band
D-LTF. Check the number of D-LTF symbols against the signaled space-time
streams; do not assume one for other modes. Locate SIG-B and data separately,
including short-GI symbol one and traveling-pilot restrictions. Validate
clean 4 and 8 MHz BCC/MCS0, then high MCS, with exact independent MPDUs.

For MU, decode SIG-B user allocation, per-user MCS/length and spatial streams.
One coherent receive channel cannot generally separate simultaneous unknown
streams. Keep a distinct unsupported result until IQ has enough coherent
channels for the advertised spatial rank and a multi-user ground truth.

## NDP MAC and sounding NDP

[IEEE P802.11ah/D0.1](https://mentor.ieee.org/802.11/dcn/13/11-13-0500-00-00ah-proposed-tgah-draft-amendment.pdf)
describes NDP MAC information in PHY signaling and no PSDU/FCS. A 1 MHz NDP
uses its own SIG layout; 2 MHz NDP MAC is distinct from an empty ordinary
data PPDU. [Keysight's 802.11ah setup](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Waveform%20Setup.htm)
also separates NDP for sounding from NDP for NDP MAC. Parse the final-standard
field layout by width and subtype, validate the SIG CRC and reserved/tail
bits, and publish `phy_event` metadata on a separate GNU Radio port. Never
put an NDP on the FCS-verified MPDU port.

The [Morse monitor path](https://github.com/MorseMicro/morse_driver/blob/main/monitor.c)
reports a zero-length PSDU with a driver-specific raw NDP field. This is a
useful independent subtype reference, but it is firmware-demodulated metadata,
not raw-IQ proof. In one synchronized private 30 s HackRF/40 s MM6108 run,
the monitor reported six NDPs; four 2 MHz records fell within IQ time. Ten
8 MHz data MPDUs and five 2 MHz beacons from the same IQ matched monitor
bytes exactly. At the four NDP times, channelized 100 µs power bins at 923,
924 and 925 MHz were at most about 1.07 times local background. No distinct
NDP burst or CRC-validated SIG was obtained; their reported receiver level
was substantially weaker than the matched local data. A higher-sensitivity,
non-clipping independent IQ capture or a known NDP MAC waveform is needed. A
third synchronized receive-only trial raised HackRF gain to LNA24/VGA4 and
recorded six 2 MHz NDPs in the monitor interval. All six NDP times again
lacked a distinct 2 MHz burst in the independent IQ. Although this recording
showed no ADC clipping, it recovered no FCS-valid 8 MHz data frames in a
five-second check, so it is not an acceptance capture for those frames.

## LDPC

LDPC is a separate FEC chain. The current SIG parser rejects its coding bit,
so BCC Viterbi is never mislabeled as LDPC. A decoder needs the applicable
parity-check matrices and code rates, shortening, puncturing, repetition and
codeword-to-OFDM mapping for the chosen width/MCS/PSDU length. Verify a
noise-free codeword syndrome and exact payload first, then FCS after the full
PHY path. A generic 802.11n LDPC library cannot by itself establish an S1G
frame: [this library](https://github.com/tavildar/LDPC) explicitly omits
puncturing, padding and stream parsing. MathWorks' S1G generator is BCC-only;
Keysight's advanced 802.11ah mode documents LDPC vectors. Do not ship an
LDPC branch without an independent vector for each code-rate family and at
least two payload lengths crossing codeword boundaries.

## Spatial streams, STBC, beamforming and MU

The [S1G configuration model](https://www.mathworks.com/help/wlan/ref/wlans1gconfig.html)
allows up to four space-time streams, explicit TX antennas, spatial mapping,
STBC, beamforming and multiple users. STBC doubles space-time streams for a
single spatial stream; spatial multiplexing requires channel estimates and
separation per stream. Implement and test these as separate modes. A one-
channel HackRF plus the local single-stream MM6108 cannot validate spatial
multiplexing or distinguish several concurrent MU users. Two or more phase-
coherent RX channels and known multi-antenna waveforms are the acceptance
fixture; single-RX STBC may be testable with a labelled two-TX vector. Reject
unknown SIG combinations explicitly.

## Guard interval, aggregation, MCS8/9 and full 8 MHz reliability

[MathWorks' S1G configuration](https://www.mathworks.com/help/wlan/ref/wlans1gconfig.html)
states that the first data OFDM symbol keeps the long GI even when short GI
is configured. The local 2 MHz MCS1 test recovered two long and two short GI
probes, with one submitted short-GI probe missing. Extend to 1/4/8 MHz and
long payloads using labelled vectors, then measure sample-clock error and
symbol-timing drift. A single FCS pass is format proof, not a loss estimate.

[Keysight's A-MPDU description](https://helpfiles.keysight.com/csg/n7617/Content/Main/Aggregation%20MPDU.htm)
specifies a four-byte delimiter per member and four-byte alignment padding
except after the last member. Existing 2 MHz long-frame members match the
public PCAP; a parser also preserves earlier FCS-valid members when a later
delimiter fails. Close extraction with independently labelled two-, three-
and maximum-practical-member vectors across 1/2/4/8 MHz, including EOF,
padding, corrupt middle delimiters and per-member FCS failures.

MCS8/9 require 256-QAM. The code has constellation paths, but the local
MM6108 preset TX rejects them. Generate independent MCS8/9 BCC vectors and
check exact MPDUs over multiple widths and payload lengths. At 8 MHz MCS4/5,
low/intermediate-gain local probes now pass FCS, but yield varies. The CLI
aligns each input window to the channelizer's absolute sample phase, bringing
the previously missed MCS5 frame into ordinary output. Continue with
labelled repetitions, channel-estimate EVM, ADC clipping count,
payload-bit error location and matched monitor packet counts before
claiming a packet-error rate. Do not normalize away missed transmissions by
counting only CRC-valid SIG candidates.

## Impairments and continuous capture

Use the same labelled clean vector under controlled SNR, CFO, sampling-clock
offset, multipath, adjacent-channel interference and clipping sweeps. Record
detected candidates, valid SIGs, FCS-valid MPDUs, false events, and missing
expected frames. The live Pi path must count SDR/USB overruns and GNU Radio
queue drops, bound processing latency and memory, and survive a sustained
10 Msps capture with all expected packets accounted for. The current offline
and stream benchmarks are useful baselines, not that acceptance test. No
active undervoltage alert was observed during the synchronized run; historic
boot-only `get_throttled` bits are not a reason to block this work.

A bounded live 10 Msps HackRF/OsmoSDR graph showed why file replay alone is
insufficient: its default receive ring printed 38 overflow markers. With 512
source buffers, two 30-second live trials printed zero overflow markers and
recorded about 299 million complex samples each. In the first, 55 decoded
MPDUs exactly matched the independent monitor, but four of 59 monitor data
frames in the graph interval were absent. A second trial at higher LNA gain
had substantially different monitor traffic and signal level, so it cannot
isolate a sensitivity effect. Accept live operation only after a stable
labelled reference, explicit source drop accounting, and repeatable packet
loss/false-alarm measurements; zero printed overflows alone is insufficient.

## Acceptance order

1. Obtain/export independent clean BCC vectors for wide SU long, all GI widths,
   MCS8/9 and multi-member aggregates; automate exact MPDU comparisons.
2. Obtain NDP MAC IQ with known subtype/bit fields and CRC, then add a
   separate typed PHY-event port and match an independent decoder.
3. Obtain advanced LDPC and multi-antenna/MU vectors before implementing
   their code paths; validate codeword and stream stages separately.
4. Quantify high-rate 8 MHz packet loss with simultaneous reference capture,
   then run controlled impairments.
5. Add hardware loss counters and demonstrate sustained 10 Msps operation.

Until those gates pass, publish only the measured subset in `PHY_STATUS.md`.
