# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-check 8 MHz BCC DATA against an independently specified encoder.

The encoder follows the Milos et al. MIT-licensed 802.11ah PHY simulator's
scrambler, puncturing, 26-column interleaver, and Gray-QAM bit grouping. This
is a clean DATA-field fixture, not an independent full-PPDU or RF vector:
LTF training samples come from the receiver's documented LTF template, and
STF/SIG detection is outside this test.
"""

import binascii
import json

import numpy as np
from gnuradio.halow_mesh import phy


MCS = {4: (4, (3, 4)), 5: (6, (2, 3)), 7: (6, (5, 6))}
PUNCTURE = {
    (3, 4): (1, 1, 1, 0, 0, 1),
    (2, 3): (1, 1, 1, 0),
    (5, 6): (1, 1, 1, 0, 0, 1, 1, 0, 0, 1),
}
DATA_BINS = np.array([
    k for k in range(-122, 123)
    if abs(k) > 1 and k not in (-103, -75, -39, -11, 11, 39, 75, 103)
])
PILOTS = np.array((-103, -75, -39, -11, 11, 39, 75, 103))
PILOT_BASE = np.array((1, 1, 1, -1, -1, 1, 1, 1))
PILOT_POLARITY = (1, 1, 1, 1, -1, -1, -1, 1)
NFFT, CP, SYMBOL = 256, 64, 320
FREQUENCIES = np.fft.fftshift(np.fft.fftfreq(NFFT))


def _encoder_bits(frame, mcs):
    bits_per_tone, rate = MCS[mcs]
    coded_per_symbol = 234 * bits_per_tone
    data_per_symbol = coded_per_symbol * rate[0] // rate[1]
    mpdu_bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8)).reshape(-1, 8)[:, ::-1].ravel()
    payload = np.r_[np.zeros(8, np.uint8), mpdu_bits, np.zeros(6, np.uint8)]
    payload = np.r_[payload, np.zeros((-len(payload)) % data_per_symbol, np.uint8)]

    # Direct algorithmic translation of the independent simulator's LFSR.
    seed = (1, 0, 1, 1, 1, 0, 1)
    shift = np.zeros(7, np.uint8)
    scrambled = np.empty(len(payload), np.uint8)
    for index, bit in enumerate(payload):
        feedback = seed[index] if index < 7 else int(shift[3] ^ shift[6])
        scrambled[index] = bit ^ feedback
        shift[1:] = shift[:-1]
        shift[0] = feedback
    tail = 8 + 8 * len(frame)
    scrambled[tail:tail + 6] = 0

    # K=7, octal 133/171 convolutional coding, then rate-dependent puncture.
    state = 0
    encoded = np.empty(2 * len(scrambled), np.uint8)
    for index, bit in enumerate(scrambled):
        current, prior = int(bit), state
        encoded[2 * index] = current ^ (prior & 1) ^ ((prior >> 1) & 1) ^ ((prior >> 3) & 1) ^ ((prior >> 4) & 1)
        encoded[2 * index + 1] = current ^ (prior & 1) ^ ((prior >> 3) & 1) ^ ((prior >> 4) & 1) ^ ((prior >> 5) & 1)
        state = (current << 5) | (prior >> 1)
    pattern = np.asarray(PUNCTURE[rate], dtype=bool)
    keep = np.resize(pattern, len(encoded))
    punctured = encoded[keep]
    assert len(punctured) % coded_per_symbol == 0

    # Milos et al.: rectangular first permutation and long-run second one.
    positions = np.arange(coded_per_symbol)
    rows, columns = coded_per_symbol // 26, 26
    first = rows * (positions % columns) + positions // columns
    stride = max(1, bits_per_tone // 2)
    second = stride * (positions // stride) + (
        (positions + coded_per_symbol - (columns * positions) // coded_per_symbol) % stride
    )
    interleaved = np.empty_like(punctured.reshape(-1, coded_per_symbol))
    for index, source in enumerate(punctured.reshape(-1, coded_per_symbol)):
        stage = np.empty(coded_per_symbol, np.uint8)
        stage[first] = source
        interleaved[index, second] = stage
    return interleaved


def _gray_decode(value):
    binary = value
    while value:
        value >>= 1
        binary ^= value
    return binary


def _qam(bits, bits_per_tone):
    side = 1 << (bits_per_tone // 2)
    output = np.empty(len(bits) // bits_per_tone, complex)
    for index, word in enumerate(bits.reshape(-1, bits_per_tone)):
        label = 0
        for bit in word:
            label = (label << 1) | int(bit)
        i = 2 * _gray_decode(label >> (bits_per_tone // 2)) - (side - 1)
        q = 2 * _gray_decode(label & (side - 1)) - (side - 1)
        output[index] = complex(i, q)
    return output / np.sqrt(2 * (side * side - 1) / 3)


def _place_fft(samples, start, spectrum, correction):
    corrected = spectrum * np.exp(-2j * np.pi * correction * FREQUENCIES)
    samples[start:start + NFFT] = np.fft.ifft(np.fft.ifftshift(corrected))


def _data_field_vector(frame, mcs):
    coded = _encoder_bits(frame, mcs)
    samples = np.zeros(6 * SYMBOL + len(coded) * SYMBOL + NFFT, complex)
    ltf = np.zeros(NFFT, complex)
    for center in (-96, -32, 32, 96):
        ltf[center + phy._SUB56 + 128] = phy._LTF
    for tone, sign in phy._LTF_8_EXTRA.items():
        ltf[tone + 128] = sign
    for start in (2 * SYMBOL + 96, 3 * SYMBOL + 32):
        _place_fft(samples, start, ltf, 32)
    for index, row in enumerate(coded):
        spectrum = np.zeros(NFFT, complex)
        spectrum[DATA_BINS + 128] = _qam(row, MCS[mcs][0])
        # The two SIG symbols advance the simulator's pilot sequence.
        spectrum[PILOTS + 128] = (np.roll(PILOT_BASE, -index) *
                                  PILOT_POLARITY[index + 2])
        _place_fft(samples, (6 + index) * SYMBOL + CP // 2 + 2, spectrum, 30)
    return samples, len(coded)


def main():
    results = []
    for mcs in MCS:
        for length in (30, 484):
            body = bytes((37 * index + 19) & 255 for index in range(length - 4))
            frame = body + binascii.crc32(body).to_bytes(4, "little")
            samples, symbols = _data_field_vector(frame, mcs)
            sig = {"mcs": mcs, "length": length, "aggregation": False,
                   "short_gi": False, "ppdu_format": "S1G_SHORT"}
            recovered = phy._payload_wide(samples, 0, 0, sig, 8)
            assert recovered == [frame], (mcs, length, len(recovered))
            results.append({"mcs": mcs, "mpdu_bytes": length, "symbols": symbols,
                            "exact_fcs": True})
    print(json.dumps({"scope": "clean 8 MHz DATA field only", "results": results}))


if __name__ == "__main__":
    main()
