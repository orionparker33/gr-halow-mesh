# Raw-IQ PHY acceptance status

**Target:** receive-only IEEE 802.11ah IQ-to-MPDU decoding across 1, 2, 4, and
8 MHz, with the verified MPDU sent to this project's 802.11s MAC parser.
**Current result:** the four widths work on real Pi 5 captures in the modes
listed below. The receiver is suitable for offline analysis of those measured
modes. The 1, 2, and 4 MHz paths do not yet meet a production acceptance gate:
4 MHz high-MCS recovery is inconsistent, and live source loss is not observable
end to end. This is not a complete standards-conformant, real-time PHY receiver.

## What the receiver does

- Accepts signed 8-bit interleaved or complex IQ at an explicit sample rate,
  width, and channel-center offset. It checks Nyquist coverage and truncated
  input. The CLI scans a recording; GNU Radio accepts bounded IQ message PDUs
  or a complex sample stream segmented into overlapping windows.
- Detects S1G training fields, estimates timing and carrier offset, equalizes
  with the 1/2/4/8 MHz LTF, decodes SIG with CRC, BCC data and interleaver,
  descrambles the PSDU, and emits only MPDUs with a valid FCS.
- Supports `S1G_1M` at 1 MHz, including MCS10 repetition, single-stream BCC
  `S1G_SHORT` at 2/4/8 MHz, and single-user BCC `S1G_LONG` at 2 MHz. The
  2 MHz long path decodes SIG-A, uses D-LTF/SIG-B for the beam-changeable
  channel, and applies the same FCS gate to extracted A-MPDU members.
  Short GI has one independent local 2 MHz MCS1 trial. Wider S1G_LONG, LDPC,
  multi-stream, NDP and 16 MHz are not decoded from IQ. The local MM6108
  supports a maximum 8 MHz channel, although 802.11ah defines 16 MHz.
- Keeps 802.11s protected data opaque. `mesh_decode` requires an explicit
  mesh-BSS context to interpret QoS Mesh Control.

## Measured over-air matrix

| Width | FCS-verified from independent HackRF IQ | Remaining local evidence |
| --- | --- | --- |
| 1 MHz | MCS0–7 and MCS10 broadcast probes | Three exact-body, FCS-valid probes per MCS (27/27). Separate 480-byte MCS0/MCS10 MPDUs passed 6/6 with exact content. |
| 2 MHz | MCS0–7 broadcast probes; MCS1 short-GI probes; published S1G_SHORT and S1G_LONG frames | Three exact-body, FCS-valid probes per MCS (24/24); separate 480-byte MCS0/MCS7 MPDUs passed 6/6. Public IQ/PCAP matched 116/116, including 55 S1G_LONG frames. Short GI remains partly measured. |
| 4 MHz | MCS0–7 probes; 480-byte MCS0 data | A three-send matrix recovered 19/24 probes. Correct six-pilot rotation with a bounded phase-fit/common fallback recovered 21/24 in a separate centered-channel replay, but high-MCS loss persists. A 480-byte MCS0 trial passed 3/3 after the pilot correction; 480-byte MCS7 passed 0/3. This width is not accepted as production reliable. |
| 8 MHz | MCS0–7 probes; MCS0 mesh data | A 30-probe, non-clipping 916 MHz MCS4/5 capture contained 30/30 CRC-valid SIGs, while the unchanged decoder recovered 1/15 MCS4 and 8/15 MCS5 FCS-valid MPDUs. High-rate reliability remains unaccepted. The local TX tool rejects MCS8/9. |

A synchronous private HackRF/MM6108 capture pair had 14 overlapping 8 MHz
MCS0 data frames and seven overlapping 2 MHz MCS0 beacons. Every one of those
21 raw-IQ decodes matched the separate MM6108 monitor's MPDU bytes, including
FCS. A later 30-second pair recovered 58/58 expected 8 MHz data MPDUs and
30/30 expected 2 MHz beacons, with exact bytes and no extra 8 MHz frames.
The verified broadcast probe frames at 1/2/4/8 MHz matched
the preset body after accounting for the sequence number assigned by the TX
MAC. A valid SIG alone is never published as an MPDU.

The 1/2/4 MHz repeatability capture is private case
`halow-124-repeat-20261013T172706Z`. All 25 local three-send calls completed;
all recovered probes matched the rendered bodies after excluding the
transmitter-assigned sequence number and FCS. The selected 2 MHz channel also
contained 18 separate FCS-valid mesh beacons in the 20-second analysis window.
In the 4 MHz misses, transmitted bursts were visible; several had CRC-valid
SIG but no FCS-valid payload, with no ADC clipping at the original 8/8 dB
receiver gains. A 16/8 dB gain trial clipped about 24% of active burst samples
and yielded 0/9 MCS4–6 MPDUs. An 8/14 dB trial clipped about 1% and yielded
5/9; an 8/10 dB trial clipped about 0.05% and yielded 2/9. Centering HackRF
on the 4 MHz channel yielded 20/24 before the pilot correction and 21/24
after it. Neither gain nor centering closes the gap. The separate 480-byte
trial is private case `halow-long-20261013T173601Z`.
A further run placed the 4 MHz transmitter at 914 MHz, outside the active
924 MHz mesh channel, and centered HackRF on 914 MHz. It recovered 19/24
probes, including 0/3 MCS4, so overlap with the mesh channel does not explain
the full loss. That case is `halow-4m-isolated-20261013T174303Z`.

The finite GNU Radio complex-stream replay of the 480-byte case recovered
6/6 exact 1 MHz MPDUs in 1.3 seconds of graph time, 6/6 exact 2 MHz MPDUs
in 18.4 seconds, and the three FCS-valid 4 MHz MCS0 MPDUs in 5.3 seconds,
from 3.7 seconds of channelized IQ per width. The 2 MHz stream needed a
channel-occupancy ranking because one 100 ms window had 449 narrowband
preamble candidates and the real frame was about 211th in time order. An
independent minimum of 16 fine timing origins per selected 2 MHz raw peak
recovered a frame otherwise lost with the default eight-candidate cap. The
published 2 MHz IQ/PCAP check still matched 116/116 offline and stream after
this change. At exactly 2 Msps, a power tie-breaker also recovered 6/6 in
19.1 graph seconds. The 2 and 4 MHz stream timings do not meet live rate.

A separately published 2 MHz IQ recording by Daniel Estévez provided an
additional external check. The first two seconds yielded 116 FCS-valid MPDUs,
including 55 S1G_LONG frames; all 116 matched exact bytes in the author's
published decoded PCAP. Run
`tests/validate_public_iq.py` against the author's extracted ci16_le SigMF
data and PCAP to repeat this test. The two reference files are linked below
and are not included in this repository. The GNU Radio complex-stream block
produced all 116 exact matches when the finite recording was drained with
100 ms of zero-valued samples. Without that drain, its final partial window
lost one 109-byte PPDU starting at 1.994 seconds during graph shutdown; the
underlying IQ decoder recovered it. A private 8 MHz MCS7 frame crossing a 50 ms
stream-window edge was emitted once at the correct sample offset. At 1 Msps,
the stream block recovered all nine 1 MHz MCS0–7/10 probes once in 0.881
seconds for four seconds of recorded channelized IQ. At 4 Msps, it recovered
all eight 4 MHz MCS0–7 probes in 3.745 seconds for 3.4 seconds of channelized
IQ. A complete 8 MHz IQ-to-mesh graph emitted four mesh events from two
seconds of the synchronized capture. On a later 30-second 8 MHz complex-file
replay, the stream block emitted 58/58 exact offline-reference MPDUs in 14.0
seconds after wideband candidate ranking. The same replay without ranking
missed a frame hidden behind 200 narrowband preamble impostors in one window.

The field captures used a 10 Msps HackRF centered at 924 MHz and a Pi 5. The
radio was returned to PortaPack Mayhem mode, the MM6108 monitor and radiotap
interfaces were down, the injection gate was disabled, and the management
route remained on the Pi's built-in Wi-Fi after each run. Raw IQ, PCAP, and
device identifiers are stored only in restricted Atlas run directories.

## Remaining acceptance work

1. Independent conformance waveforms for every claimed MCS and width,
   `S1G_SHORT`/`S1G_1M`/`S1G_LONG` field variant, guard interval, aggregation,
   and malformed SIG/FCS. The local preset sender cannot exercise MCS8/9.
2. Measure packet error rate and false-alarm rate versus SNR, CFO, clock
   offset, multipath, clipping, adjacent-channel traffic, and payload size.
   Resolve 8 MHz MCS4/5 packet-loss performance with a clean, independently
   received reference before declaring broad reliability. The previous
   high-gain 916 MHz capture clipped roughly 66% of active PPDU samples and
   yielded no FCS-valid MCS4/5 payloads despite six CRC-valid SIGs. At zero
   LNA/VGA gain, clipping disappeared and one of three MCS4 plus one of three
   MCS5 probes passed FCS. At intermediate gain, the phase-aligned CLI
   recovered one of three MCS4 and two of three MCS5 probes. Every recovered
   body matched the rendered preset. A follow-up 25.218-second independent
   IQ recording included all 30 planned bursts in its first 10 seconds, with
   30/30 preambles and CRC-valid SIGs and no ADC clipping in the measured
   burst windows. Only 1/15 MCS4 and 8/15 MCS5 MPDUs passed FCS. Several
   MCS5 failures had the expected body but errors in the final FCS bytes.
   Pilot phase, soft-bit weighting, Viterbi endpoint, and LTF diagnostic
   variants did not improve recovery. The run wrapper timed out while waiting
   for its nominal 30-second recording; the 25.218-second file is sufficient
   for the 30 probes but not a 30-second capture benchmark. Resolve this
   high-rate loss with labelled waveforms and quantified error analysis.
   Evidence case: `halow-phy-mcs45-replicate-20261013T165828Z` (private IQ).
   A separate 20-second capture varied the named probe body across 1, 8,
   16, and 32 SSID bytes. All 24 bursts had the requested MCS and a CRC-valid
   SIG; the unchanged decoder recovered only two FCS-valid MPDUs, both at
   eight SSID bytes (one per MCS). Both matched the rendered body. No sampled
   burst window clipped. This further limits high-rate acceptance but does
   not by itself separate transmitter quality from receiver error.
   Evidence case: `halow-mcs45-length-20261013T170948Z` (private IQ).
   The previous 2 MHz MCS2/4/5/6/7 failure was an STF timing
   alias and is resolved on the original IQ.
   At 4 MHz, the former wideband path ignored the rotating pilot signs and
   per-symbol pilot phase slope. The corrected path recovers three exact
   480-byte MCS0 frames and one additional short probe in the centered replay.
   It still loses MCS4–6 short probes and all three 480-byte MCS7 sends on
   this local link. Obtain a stronger, independently monitored 4 MHz fixture
   and labelled high-MCS waveforms before setting a production SNR/PER gate.
3. Add wider `S1G_LONG`, LDPC, NDP, multi-stream, and 16 MHz only when the receiver
   implementation and independent test source actually support them. These
   are not silently accepted through fallback metadata.
4. Benchmark and validate sustained 10 Msps Pi 5 operation. On a busy
   30-second 8 MHz mesh recording, the sensitive default offline CLI took
   17.2 seconds using four Pi cores and recovered 58/58 exact monitor frames
   with no extras. Before lazy IQ conversion and parallel candidate decode,
   the same pass took 50.6 seconds on one core. This demonstrates offline
   throughput on one recording, not live source backpressure or losslessness.
   An optional 8 MHz spectral filter rejected narrowband candidate impostors
   while retaining these 58 frames and three MCS4/5 probes; it is disabled
   by default because a weak wideband frame under narrowband interference
   might be excluded. The GNU Radio stream block uses
   overlapping bounded windows and a raw preamble search inside its work
   thread. It processed a 30-second 8 MHz complex-file replay in 14.0
   seconds and recovered all 58 exact MPDUs after ranking dense candidates
   by channel occupancy. The 1 MHz path at exactly 1 Msps and
   4 MHz path at exactly 4 Msps use full-window detection to avoid spurious
   preamble candidates from a frequency-shifted SDR center spur. The 4 MHz
   stream result above was slightly slower than recorded duration. Hardware
   overrun detection and lossless live flow control remain unimplemented in
   the block. A live HackRF/OsmoSDR source printed 38 overflow markers with
   its default ring and delivered 294.5 million samples in 30 seconds.
   With 512 source buffers it printed zero overflow markers and delivered
   299.5 million samples in 30 seconds; 55 FCS-valid outputs matched the
   independent MM6108 monitor exactly, but four of 59 monitor data frames
   in the graph interval were absent. Three had no raw STF candidate in the
   recorded IQ and one had candidates but no FCS-valid payload. A repeat at
   higher LNA gain also printed zero overflows, but the decoded signal level
   and monitor frame count changed enough to invalidate a gain comparison.
   Neither run establishes a controlled packet-error rate or live losslessness.

## Format-gap research and acceptance path

| Gap | What the format requires | Current evidence and next acceptance gate |
| --- | --- | --- |
| `S1G_LONG` | SIG-A in the omni portion, then D-STF, one or more D-LTFs, SIG-B and data in the beam-changeable portion. SU SIG-B repeats D-LTF1; MU SIG-B carries user information. | **2 MHz SU implemented:** the first two seconds of the external IQ source yield 55 FCS-valid S1G_LONG MPDUs, all exact PCAP matches. The published source exercises MCS4/6/7, traveling pilots, and aggregation. For 4/8 MHz and MU, obtain independent format-labelled IQ plus reference MPDUs, implement the full-band D-LTF and per-user SIG-B/spatial path, and demand exact matches. Do not infer wide or MU support from the 2 MHz result. |
| NDP | The MAC information is encoded in the PHY signaling field; there is no data field or MPDU FCS to pass through the existing `out` port. | The MM6108 monitor PCAP can expose NDP metadata, but raw-IQ decoding currently rejects NDP SIG. A synchronized moderate-gain run found six monitor NDPs, four within IQ time; none of those four rose distinctly above the HackRF channelized noise floor, while 10 data MPDUs and five beacons matched exact bytes. A higher-gain repeat observed six NDPs in monitor records but again no distinct NDP burst in IQ; that IQ did not pass a data-frame FCS check. Obtain a detectable independent NDP MAC IQ fixture, then add a separately typed CRC-validated PHY-event output. Do not label an NDP as an FCS-verified MPDU. |
| LDPC | A different FEC encoder/decoder and codeword/shortening/puncturing rules replace the BCC Viterbi path. | SIG currently rejects LDPC. The local MM6108 preset sender cannot generate an independent LDPC fixture; MathWorks' S1G waveform configuration supports BCC only. Keysight documents 802.11ah LDPC in its advanced waveform mode. Obtain exported IQ plus exact expected payloads, then implement codeword recovery and test FCS over rates and payload sizes. |
| Spatial streams, STBC and MU | Additional LTFs and spatial mapping require channel estimates for each stream; STBC needs its own combining path, and MU needs per-user signaling. | The local MM6108 is a one-stream transmitter and HackRF is a one-channel receiver. Obtain coherent multi-channel IQ and independent output for spatial multiplexing; obtain a multi-antenna STBC/MU vector for their separate paths. Preserve explicit SIG rejection meanwhile. |
| Short guard interval | Data symbol 1 still has a long guard interval; subsequent symbols can use the short interval. | The 2 MHz MCS1 local trial recovered two long-GI and two short-GI broadcast probes with valid FCS and exact frame body (ignoring transmitter-assigned sequence/FCS); one additional submitted short-GI probe was not recovered. Add independent 1/4/8 MHz vectors, long payloads and timing/clock impairments before claiming a general short-GI receiver. |
| A-MPDU | SIG length becomes a symbol count; each member has a delimiter, alignment/padding and its own MPDU FCS. | Published 2 MHz S1G_LONG aggregated PPDUs yielded exact PCAP members. The parser now preserves earlier FCS-valid members when a later delimiter is corrupt or truncated. A corpus with known multi-member aggregates, malformed intermediate delimiters, and EOF padding is still needed to establish complete extraction at each width. |
| 8 MHz MCS4/5 and high MCS | 16-QAM 3/4 and 64-QAM 2/3 need accurate wideband channel estimation and sufficiently clean IQ. MCS8/9 use 256-QAM. | MCS4 and MCS5 have independently captured, FCS-valid, exact-body local probes at 916 MHz. A 66% ADC clipping fraction explained the all-fail high-gain trial; zero/intermediate gain each recovered a subset. The phase-aligned CLI recovers three of six intermediate-gain sends. Quantify EVM and packet loss with a non-overloaded receiver and a simultaneous independent monitor reference. Local MM6108 preset TX rejects MCS8/9; use an independent 256-QAM vector before claiming them. |
| Impairments and live rate | A practical receiver needs bounded false alarms and packet loss under noise, CFO, clock error, multipath, adjacent traffic and clipping, plus lossless stream handling. | The 30-second offline 8 MHz benchmark met recorded duration and exact monitor matching. A live 10 Msps source needed a 512-buffer ring to avoid OsmoSDR overflow markers in two bounded trials, and four of 59 independently monitored data frames were absent from the first zero-overflow recording. Build labelled clean/impairment IQ fixtures with expected MPDUs, measure detection and FCS-verified packet error/false-alarm rates, then expose explicit dropped-sample counters and test stable continuous capture. |

The 2 MHz preamble correction is deliberately FCS-gated: normalized STF
correlation peaks can fall on several points of a broad plateau. A SIG CRC can
pass at a periodic timing alias while payload data fails FCS. The receiver now
tries four bounded preamble origins for 2 MHz and emits only FCS-valid MPDUs.
This repaired all five failing high-rate probes on the original local matrix
and 116/116 exact external PCAP matches in a two-second published sample. An
8 MHz fallback also tests later full-band FFT origins only after the normal
timing search fails; FCS and an exact probe-body match validated its added
MCS4 recovery. Input windows now align to the channelizer's absolute
resampling phase, resolving the separate MCS5 window-phase miss.

## Sources and provenance

- [IEEE 802.11ah decoding analysis by Daniel Estévez](https://destevez.net/2025/01/decoding-ieee-802-11ah/) and the linked MIT-licensed notebook supply the 2 MHz training, synchronization, SIG, and BCC basis.
- [MathWorks S1G PPDU structure](https://www.mathworks.com/help/wlan/gs/s1g-ppdu-structure.html) describes the three preamble formats and the SU/MU long fields; [S1G waveform generation](https://www.mathworks.com/help/wlan/ug/802-11ah-waveform-generation.html) documents traveling pilots; [S1G configuration](https://www.mathworks.com/help/wlan/ref/wlans1gconfig.html) documents short-GI symbol 1 and its BCC-only generator limit.
- [IEEE P802.11ah/D0.1](https://mentor.ieee.org/802.11/dcn/13/11-13-0500-00-00ah-proposed-tgah-draft-amendment.pdf) describes NDP signaling and optional coding/spatial modes. It is an early draft, not final normative text; verify field details against the current standard before implementing NDP or LDPC.
- [Morse Micro MM6108 data sheet](https://www.morsemicro.com/resources/datasheets/chips/MM6108_Data_Sheet.pdf) is the primary source for this local chip's 1/2/4/8 MHz, single-stream MCS0–7/10 limits.
- [Estévez's published IQ archive](https://nas.destevez.net/~daniel/IEEE_802.11ah/) and [decoded PCAP](https://github.com/daniestevez/jupyter_notebooks/blob/master/IEEE_802.11ah/802_11_ah.pcap) supply the external 2 MHz acceptance pair.
- [gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) is a GPL-3.0-or-later 1 MHz implementation used to cross-check S1G_1M LTF and SIG repetition/interleaving.
- [Format-gap research](FORMAT_GAP_RESEARCH.md) identifies independently usable vector sources, separates NDP MAC from sounding NDP, and defines acceptance tests for each open format through 8 MHz.
- The [IEEE TGah specification framework](https://ie.u-ryukyu.ac.jp/~wada/system15/11-11-1137-15-00ah-specification-framework-for-tgah%20(2).pdf) and [Keysight 802.11ah signal configuration](https://helpfiles.keysight.com/csg/n7617b/Content/Main/802.11ah%20Signal%20Configuration.htm) describe format and width choices.
- See `THIRD_PARTY_NOTICES.md` for software attribution and license terms.
