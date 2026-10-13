# Raw-IQ PHY receiver status

**Target:** independent, receive-only IEEE 802.11ah PPDU-to-MPDU decoding for 1, 2, 4, and 8 MHz channels, feeding this project's `mesh_decode` PDU input. **Current status:** not implemented or production ready. The installed MM6108 PCAP source uses the radio's PHY decoder and is a separate, validated path.

## Verified reference and capture quality

- The local MM6108 monitor path received 8 MHz MCS 0 protected QoS data and 2 MHz S1G beacons on the scoped 924 MHz operating channel. Those are PHY-decoded references, not raw-IQ results.
- A simultaneous 10 Msps, 8 MHz-filter HackRF IQ sample and MM6108 PCAP capture were recorded in private Atlas run directories. The MM6108 decoded 11 8 MHz data frames and six 2 MHz beacons during the overlapping interval. HackRF burst peaks recur at the same approximately 1.024-second beacon cadence, but no IQ PPDU or FCS has been recovered. Timestamp alignment and packet identity require further verification.
- The first HackRF IQ capture was badly clipped during strong bursts. A zero-gain retry had insufficient visible signal. A third capture at 8 dB LNA and 8 dB VGA avoided clipping, with only a small rise over the noise floor at burst peaks. These captures are development evidence, not a validated production test vector.

## Receiver contract

1. Ingest interleaved signed 8-bit or complex float IQ with explicit sample rate, center frequency, gain, and time origin. Reject missing or inconsistent metadata, clipping, truncated samples, and rate mismatches before claiming a decoded frame.
2. Channelize and resample to nominal S1G widths. At 8 MHz, the useful FFT has 256 samples and a 31.25 kHz subcarrier spacing; narrower widths scale to 128/64/32 FFT points at the same spacing. Handle primary-channel placement, short and long guard intervals, and 1 MHz special cases separately.
3. Detect candidate S1G preambles with timing and CFO estimation. Reject narrowband periodic interferers; an autocorrelation peak alone is not a packet. Use the appropriate S1G STF/LTF and SIG field for each PPDU format.
4. Equalize, track pilots and residual CFO/SFO, decode SIG fields and MCS/length, then demap, deinterleave, decode FEC, descramble, and validate PSDU/FCS. Emit an MPDU only after FCS passes. Preserve receiver metadata and reason-coded reject counters.
5. Feed verified MPDUs to `mesh_decode`. Protected 802.11s data stays encrypted unless a separate, authorized decryption stage supplies keys. No protocol field should be guessed from signal energy alone.

## Production acceptance gates

- Independent conformance vectors for every supported width and PPDU format, including 8 MHz MCS 0 through 9, guard intervals, payload lengths, FEC modes, and malformed SIG/FCS cases. Verify the generated waveforms against a second implementation or known-good instrument before using them as ground truth.
- Deterministic tests at synchronization, SIG, equalizer, FEC, and FCS boundaries, with controlled CFO, sample-rate offset, multipath, noise, clipping, and adjacent-channel signals. Report detection false alarms, miss rate, packet error rate, and throughput versus SNR, rather than a single successful decode.
- At least one real over-the-air 8 MHz MPDU recovered directly from IQ, CRC-checked and matched by timestamp/length/addresses to an independent MM6108 reference. Repeat for 1, 2, and 4 MHz and for both S1G beacon and data formats.
- Sustained Pi 5 operation at the full capture rate without dropped samples or runaway memory/CPU usage. Record hardware, gain, antenna, regional channel, clock error, and capture loss. Keep raw test captures private; publish only synthetic or scrubbed fixtures with provenance.

## Source basis

- [IEEE 802.11ah 1 MHz GNU Radio implementation](https://github.com/irongiant33/gr-ieee802-11ah): useful baseline, explicitly limited to 1 MHz PPDUs and hard-coded 32-point paths.
- [MathWorks S1G receiver function map](https://www.mathworks.com/help/wlan/802.11ah-reception.html) and [S1G OFDM information](https://www.mathworks.com/help/wlan/ref/wlans1gofdminfo.html): independent field, synchronization, and width references; no proprietary code is copied.
- [GNU Radio OFDM receiver](https://wiki.gnuradio.org/index.php?title=OFDM_Receiver): reusable DSP concepts, but its generic framing is not an S1G PHY decoder.
