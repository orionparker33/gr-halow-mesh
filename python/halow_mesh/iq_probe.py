# SPDX-License-Identifier: GPL-3.0-or-later
"""Development diagnostic for S1G-like OFDM symbols in signed 8-bit IQ.

This detects a 32 us OFDM useful-symbol repetition, not an 802.11ah packet.
Only an independently validated S1G SIG/PSDU/FCS chain can claim a decode.
"""

import numpy as np


def _moving_sum(x, count):
    prefix = np.empty(len(x) + 1, dtype=x.dtype)
    prefix[0] = 0
    np.cumsum(x, out=prefix[1:])
    return prefix[count:] - prefix[:-count]


def inspect_iq(samples, sample_rate):
    """Return best long-GI CP correlation and FFT spread in a bounded window.

    ``samples`` is Nx2 signed I/Q. A narrow tone may correlate with any lag,
    so effective FFT bins are reported alongside the correlation score.
    """
    samples = np.asarray(samples)
    if samples.ndim != 2 or samples.shape[1] != 2:
        raise ValueError("samples must be Nx2 I/Q")
    if not 1e6 <= sample_rate <= 25e6:
        raise ValueError("sample rate outside supported diagnostic range")
    lag = round(sample_rate * 32e-6)
    guard = round(sample_rate * 8e-6)
    if len(samples) < lag + guard + lag:
        raise ValueError("IQ window too short")
    values = samples.astype(np.float32)
    dc = values.mean(axis=0)
    centered = values - dc
    signal = centered[:, 0] + 1j * centered[:, 1]
    products = signal[:-lag] * np.conj(signal[lag:])
    pair_power = (np.abs(signal[:-lag]) ** 2 + np.abs(signal[lag:]) ** 2) * 0.5
    corr = _moving_sum(products, guard)
    power = _moving_sum(pair_power, guard)
    valid = len(signal) - 2 * lag - guard + 1
    scores = np.abs(corr[:valid]) / np.maximum(power[:valid], 1e-9)
    peak = int(np.argmax(scores))
    symbol = signal[peak + guard:peak + guard + lag]
    bins = np.abs(np.fft.fft(symbol)) ** 2
    total = float(bins.sum())
    spread = float(total ** 2 / np.sum(bins ** 2)) if total else 0.0
    return {
        "sample_offset": peak,
        "cp_score": round(float(scores[peak]), 5),
        "effective_fft_bins": round(spread, 2),
        "dc_iq": [round(float(x), 3) for x in dc],
        "clipped_fraction": round(float(np.mean(np.any(np.abs(values) >= 126, axis=1))), 6),
        "useful_symbol_samples": lag,
        "guard_samples": guard,
    }
